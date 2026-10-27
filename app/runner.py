"""Run a student submission against an assignment's exercise tests.

Safety model: the submission runs in a *separate process* with a hard timeout,
in a temp directory, with network access disabled via a sitecustomize shim.
Never exec() submitted code in this interpreter — an infinite loop would hang
the server and the code could read application state.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.db import ROOT

DEFAULT_TIMEOUT = 30

#: Dropped into the temp dir so the submission cannot phone home.
#: Blocks outbound connections without replacing the socket *class* — ssl.py
#: does `class SSLSocket(socket)`, so the type must stay a type. Patching the
#: connect methods stops the traffic while keeping the class hierarchy intact.
NO_NETWORK_SHIM = '''
import socket

_MSG = "network access is disabled while running submissions"


def _deny(*args, **kwargs):
    raise OSError(_MSG)


socket.socket.connect = _deny
socket.socket.connect_ex = _deny
socket.create_connection = _deny
'''


@dataclass
class RunResult:
    passed: int
    total: int
    timed_out: bool
    output: str

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.total > 0 and self.passed == self.total


_COUNT = re.compile(r"(\d+) (passed|failed|errors?)\b")
#: pytest's final line, e.g. "1 failed, 2 passed in 0.05s" (-q) or the same
#: wrapped in "=====". Anchoring on "in <time>s" keeps a submission that
#: prints "3 passed" from inflating its own score.
_SUMMARY_LINE = re.compile(r"^=*\s*\d+ \w+.* in [\d.]+s\b")


def _parse_counts(output: str) -> tuple[int, int]:
    """Extract (passed, total) from pytest's final summary line."""
    for line in reversed(output.splitlines()):
        if not _SUMMARY_LINE.match(line.strip()):
            continue
        passed = failed = 0
        for n, kind in _COUNT.findall(line):
            if kind == "passed":
                passed = int(n)
            else:
                failed += int(n)
        return passed, passed + failed
    return 0, 0


#: Environment variables a submission never needs and must not be able to read.
_SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)


def _sandbox_env(workdir: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    env["PYTHONPATH"] = str(workdir)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_submission(
    submission_path: Path,
    tests_dir: Path,
    timeout: int = DEFAULT_TIMEOUT,
    target_name: str = "solution.py",
) -> RunResult:
    """Copy submission + tests into a scratch dir and run pytest there."""
    submission_path = Path(submission_path)
    tests_dir = Path(tests_dir)

    if not submission_path.is_file():
        return RunResult(0, 0, False, f"submission not found: {submission_path}")
    if not tests_dir.is_dir():
        return RunResult(0, 0, False, f"tests directory not found: {tests_dir}")

    workdir = Path(tempfile.mkdtemp(prefix="mlos-run-"))
    try:
        shutil.copy(submission_path, workdir / target_name)
        shutil.copytree(tests_dir, workdir / "tests", dirs_exist_ok=True)
        (workdir / "sitecustomize.py").write_text(NO_NETWORK_SHIM, encoding="utf-8")

        env = _sandbox_env(workdir)

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "tests", "-q", "--no-header", "-p", "no:cacheprovider"],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                0,
                0,
                True,
                f"TIMED OUT after {timeout}s — your code probably has an infinite loop "
                "or is waiting on input.",
            )

        output = (proc.stdout or "") + (proc.stderr or "")
        passed, total = _parse_counts(output)
        return RunResult(passed, total, False, output.strip()[:20000])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def resolve(path_str: str) -> Path:
    """Resolve a curriculum-relative path against the project root."""
    p = Path(path_str)
    return p if p.is_absolute() else ROOT / p
