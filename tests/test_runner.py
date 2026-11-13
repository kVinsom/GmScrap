import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "project_test_runner", ROOT / "run_tests.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class TestRunnerTests(unittest.TestCase):
    def test_missing_optional_test_dependencies_fail_instead_of_skipping(self):
        errors = io.StringIO()
        with (
            patch.object(runner.importlib.util, "find_spec", return_value=None),
            patch.object(runner.subprocess, "run") as run,
            redirect_stderr(errors),
        ):
            self.assertEqual(runner.main(), 1)
        run.assert_not_called()
        self.assertIn("requirements-dev.txt", errors.getvalue())

    def test_success_uses_current_interpreter_and_project_paths(self) -> None:
        with (
            patch.object(
                runner.subprocess, "run", return_value=Mock(returncode=0)
            ) as run,
            patch.dict(os.environ, {"PYTHONPATH": "existing"}),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(runner.main(), 0)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(
            [call.args[0][2:] for call in run.call_args_list],
            [
                ["unittest", "discover", "-s", "tests", "-v"],
                ["ruff", "check", "."],
                ["ruff", "format", "--check", "."],
            ],
        )
        for call in run.call_args_list:
            self.assertEqual(call.args[0][:2], [sys.executable, "-m"])
            self.assertEqual(call.kwargs["cwd"], ROOT)
            self.assertEqual(
                call.kwargs["env"]["PYTHONPATH"],
                str(ROOT / "src") + os.pathsep + "existing",
            )

    def test_any_failed_check_returns_nonzero_and_runs_remaining_checks(self) -> None:
        for codes in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)):
            with self.subTest(codes=codes):
                errors = io.StringIO()
                with (
                    patch.object(
                        runner.subprocess,
                        "run",
                        side_effect=[Mock(returncode=code) for code in codes],
                    ) as run,
                    redirect_stdout(io.StringIO()),
                    redirect_stderr(errors),
                ):
                    self.assertEqual(runner.main(), 1)
                self.assertEqual(run.call_count, 3)
                self.assertIn("Failed:", errors.getvalue())
