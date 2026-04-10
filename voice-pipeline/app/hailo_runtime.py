import os
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


def resolve_hailo_runtime_from_env() -> HailoRuntimeConfig:
    apps_dir = Path(os.getenv("HAILO_APPS_DIR", "/home/siddy/workspace/hailo-apps")).expanduser()
    setup_env_file = apps_dir / "setup_env.sh"
    explicit_python = os.getenv("HAILO_VENV_PYTHON", "").strip()
    whisper_cmd = os.getenv("HAILO_WHISPER_CMD", DEFAULT_WHISPER_CMD)

    if explicit_python:
        python_path = Path(explicit_python).expanduser()
        candidates = [python_path]
    else:
        candidates = _candidate_python_paths(apps_dir)

    candidate_paths = _dedupe_paths(candidates)
    valid_python = next(
        (
            candidate
            for candidate in candidate_paths
            if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK)
        ),
        None,
    )

    if valid_python is None:
        checked = ", ".join(str(path) for path in candidate_paths)
        hint = (
            "Setze HAILO_VENV_PYTHON auf einen gültigen, ausführbaren Interpreter "
            "im Hailo-venv."
        )
        raise FileNotFoundError(f"Kein ausführbarer Hailo-Python-Interpreter gefunden. Geprüft: {checked}. {hint}")

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
