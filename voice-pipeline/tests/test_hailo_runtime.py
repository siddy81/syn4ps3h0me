import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.hailo_runtime import HailoRuntimeConfig, resolve_hailo_runtime_from_env, validate_hailo_runtime


class HailoRuntimeResolutionTests(unittest.TestCase):
    def test_resolve_uses_first_existing_executable_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            apps_dir = Path(tmp)
            (apps_dir / "setup_env.sh").write_text("#!/usr/bin/env bash\n")
            venv_python = apps_dir / ".venv/bin/python"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("#!/usr/bin/env bash\n")
            venv_python.chmod(stat.S_IRWXU)

            with patch.dict(
                os.environ,
                {
                    "HAILO_APPS_DIR": str(apps_dir),
                    "HAILO_VENV_PYTHON": "",
                },
                clear=False,
            ):
                runtime = resolve_hailo_runtime_from_env()

            self.assertEqual(runtime.hailo_python, venv_python)

    def test_resolve_fails_with_all_checked_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            apps_dir = Path(tmp)
            with patch.dict(
                os.environ,
                {
                    "HAILO_APPS_DIR": str(apps_dir),
                    "HAILO_VENV_PYTHON": "",
                },
                clear=False,
            ):
                with self.assertRaises(FileNotFoundError) as context:
                    resolve_hailo_runtime_from_env()

        message = str(context.exception)
        self.assertIn("Geprüft:", message)
        self.assertIn("venv_hailo_apps/bin/python", message)


class HailoRuntimeValidationTests(unittest.TestCase):
    def test_validate_rejects_non_executable_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            apps_dir = Path(tmp)
            setup_env = apps_dir / "setup_env.sh"
            setup_env.write_text("#!/usr/bin/env bash\n")
            py_path = apps_dir / "venv_hailo_apps/bin/python"
            py_path.parent.mkdir(parents=True, exist_ok=True)
            py_path.write_text("#!/usr/bin/env bash\n")
            py_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            runtime = HailoRuntimeConfig(
                hailo_apps_dir=apps_dir,
                setup_env_file=setup_env,
                hailo_python=py_path,
                whisper_cmd_template="echo test",
            )

            with self.assertRaises(PermissionError):
                validate_hailo_runtime(runtime)


if __name__ == "__main__":
    unittest.main()
