import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import windows_runtime as runtime


class WindowsRuntimeTests(unittest.TestCase):
    def test_python_315_and_prerelease_are_rejected(self):
        for version, release in [([3, 15], "final"), ([3, 13], "candidate"), ([3, 10], "final")]:
            result = Mock(returncode=0, stdout=json.dumps({"version": version, "release": release, "python": "python.exe"}))
            with patch.object(runtime.subprocess, "run", return_value=result):
                self.assertIsNone(runtime.probe(["python"]))

    def test_probe_works_on_actual_supported_interpreter(self):
        if sys.version_info[:2] not in runtime.SUPPORTED:
            self.skipTest("Test host is not on a supported version")
        found = runtime.probe([sys.executable])
        self.assertEqual(found[1], sys.version_info[:2])
        self.assertEqual(found[0], Path(sys.executable))

    def test_supported_launcher_is_selected_before_default_python(self):
        def probe(command):
            if command == ["py", "-3.12"]:
                return Path("supported-python.exe"), (3, 12)
            return None
        with patch.object(runtime, "probe", side_effect=probe) as detect:
            self.assertEqual(runtime.find_python(), (Path("supported-python.exe"), (3, 12)))
        self.assertEqual(detect.call_args_list[0].args[0], ["py", "-3.13"])
        self.assertEqual(detect.call_args_list[1].args[0], ["py", "-3.12"])

    def test_no_supported_python_does_not_start_dependency_install(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runtime, "find_python", return_value=None), patch.object(runtime.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "3.15"):
                runtime.install(Path(folder))
            run.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_install_preserves_old_environment_and_uses_binary_packages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / ".venv" / "user-file.txt"
            old.parent.mkdir()
            old.write_text("keep me")
            with patch.object(runtime, "find_python", return_value=(Path("python313.exe"), (3, 13))), patch.object(runtime.subprocess, "run", return_value=Mock(returncode=0)) as run:
                self.assertEqual(runtime.install(root), 0)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0], ["python313.exe", "-m", "venv", str(root / ".venv-3.13")])
            pip = next(command for command in commands if "pip" in command)
            self.assertIn("--only-binary=:all:", pip)
            self.assertEqual(old.read_text(), "keep me")
            marker = json.loads((root / ".afzal-runtime.json").read_text())
            self.assertEqual(marker["python"], ".venv-3.13/Scripts/python.exe")

    def test_incomplete_environment_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".venv-3.13").mkdir()
            kept = root / ".venv-3.13" / "keep.txt"
            kept.write_text("existing files")
            self.assertEqual(runtime.environment_directory(root, (3, 13)), root / ".venv-3.13-2")
            self.assertEqual(kept.read_text(), "existing files")

    def test_dependency_failure_does_not_mark_installation_complete(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runtime, "find_python", return_value=(Path("python313.exe"), (3, 13))):
            def run(command, **kwargs):
                if "pip" in command:
                    raise subprocess.CalledProcessError(1, command)
                return Mock(returncode=0)
            with patch.object(runtime.subprocess, "run", side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    runtime.install(Path(folder))
            self.assertFalse((Path(folder) / ".afzal-runtime.json").exists())

    def test_launch_uses_saved_environment_and_preserves_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            python = root / ".venv-3.13" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.touch()
            (root / ".afzal-runtime.json").write_text(json.dumps({"python": python.relative_to(root).as_posix()}))
            with patch.object(runtime, "probe", return_value=(python, (3, 13))), patch.object(runtime.subprocess, "run", return_value=Mock(returncode=7)) as run:
                self.assertEqual(runtime.run_app(root), 7)
                self.assertEqual(run.call_args.args[0], [str(python), str(root / "main.py")])


if __name__ == "__main__":
    unittest.main()
