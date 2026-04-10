import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_WHISPER_CMD = (
    "cd {hailo_apps_dir} && source setup_env.sh && {hailo_python} -m "
    "hailo_apps.python.gen_ai_apps.simple_whisper_chat.simple_whisper_chat "
    "--audio-file {audio_path} --language {language}"
)


@dataclass(frozen=True)
class HailoRuntimeConfig:
    hailo_apps_dir: Path
    setup_env_file: Path
    hailo_python: Path
    whisper_cmd_template: str


def _candidate_python_paths(apps_dir: Path) -> list[Path]:
    return [
        apps_dir / "venv_hailo_apps/bin/python",
        apps_dir / ".venv/bin/python",
        apps_dir / "venv/bin/python",
    ]


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _is_executable_file(path: Path) -> bool:
    return path.exists() and path.is_file() and os.access(path, os.X_OK)


def _extract_executable_from_probe_output(output: str) -> Path | None:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        candidate = Path(line).expanduser()
        if _is_executable_file(candidate):
            return candidate
    return None


def _detect_python_via_setup_env(apps_dir: Path, setup_env_file: Path) -> tuple[Path | None, str]:
    if not setup_env_file.exists():
        return None, "setup_env.sh fehlt"

    cmd = (
        f"cd {shlex.quote(str(apps_dir))} && "
        f"source {shlex.quote(str(setup_env_file))} && "
        "python -c \"import sys; print(sys.executable)\""
    )
    result = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, check=False)
    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    if result.returncode != 0:
        return None, f"setup_env probe rc={result.returncode} output={output}"

    resolved = _extract_executable_from_probe_output(output)
    if resolved is None:
        return None, f"setup_env lieferte keinen ausführbaren Interpreter. output={output}"

    return resolved, f"setup_env probe ok: {resolved}"


def resolve_hailo_runtime_from_env() -> HailoRuntimeConfig:
    apps_dir = Path(os.getenv("HAILO_APPS_DIR", "/home/siddy/workspace/hailo-apps")).expanduser()
    setup_env_file = apps_dir / "setup_env.sh"
    explicit_python = os.getenv("HAILO_VENV_PYTHON", "").strip()
    whisper_cmd = os.getenv("HAILO_WHISPER_CMD", DEFAULT_WHISPER_CMD)

    candidate_paths: list[Path]
    setup_probe_hint = ""
    if explicit_python:
        candidate_paths = [Path(explicit_python).expanduser()]
    else:
        base_candidates = _candidate_python_paths(apps_dir)
        dynamic_candidates = sorted(apps_dir.glob("*/bin/python")) if apps_dir.exists() else []
        candidate_paths = _dedupe_paths([*base_candidates, *dynamic_candidates])

    valid_python = next((candidate for candidate in candidate_paths if _is_executable_file(candidate)), None)

    if valid_python is None and not explicit_python:
        detected_python, probe_message = _detect_python_via_setup_env(apps_dir, setup_env_file)
        setup_probe_hint = probe_message
        if detected_python is not None:
            valid_python = detected_python

    if valid_python is None:
        checked = ", ".join(str(path) for path in candidate_paths) or "<keine Kandidaten>"
        hint = (
            "Setze HAILO_VENV_PYTHON auf einen gültigen, ausführbaren Interpreter "
            "im Hailo-venv."
        )
        details = f"setup_env_probe={setup_probe_hint}" if setup_probe_hint else ""
        raise FileNotFoundError(
            f"Kein ausführbarer Hailo-Python-Interpreter gefunden. Geprüft: {checked}. {hint} {details}".strip()
        )

    return HailoRuntimeConfig(
        hailo_apps_dir=apps_dir,
        setup_env_file=setup_env_file,
        hailo_python=valid_python,
        whisper_cmd_template=whisper_cmd,
    )


def validate_hailo_runtime(config: HailoRuntimeConfig) -> None:
    if not config.hailo_apps_dir.exists() or not config.hailo_apps_dir.is_dir():
        raise FileNotFoundError(f"HAILO_APPS_DIR existiert nicht oder ist kein Verzeichnis: {config.hailo_apps_dir}")

    if not config.setup_env_file.exists() or not config.setup_env_file.is_file():
        raise FileNotFoundError(f"setup_env.sh nicht gefunden: {config.setup_env_file}")

    if not config.hailo_python.exists() or not config.hailo_python.is_file():
        raise FileNotFoundError(f"Hailo-Interpreter nicht gefunden: {config.hailo_python}")

    if not os.access(config.hailo_python, os.X_OK):
        raise PermissionError(f"Hailo-Interpreter ist nicht ausführbar: {config.hailo_python}")
