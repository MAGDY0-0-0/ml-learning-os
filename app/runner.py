"""Run a student submission against an assignment's hidden tests.

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


_SUMMARY = re.compile(r"(\d+) (passed|failed|error|errors)")


def _parse_counts(output: str) -> tuple[int, int]:
    """Extract (passed, total) from pytest's summary line."""
    passed = failed = 0
    for line in output.splitlines():
        if " passed" in line or " failed" in line or " error" in line:
            for n, kind in _SUMMARY.findall(line):
                if kind == "passed":
                    passed = int(n)
                elif kind.startswith("error"):
                    failed += int(n)
                else:
                    failed = int(n)
    return passed, passed + failed


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

        env = dict(os.environ)
        env["PYTHONPATH"] = str(workdir)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

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
