"""Point the app at a throwaway, freshly seeded database before anything imports it.

Without this the suite read and wrote the developer's real data/app.db, and on a
fresh clone (CI) every unit/project/assignment page silently redirected to "/"
because nothing was seeded — so the page tests were testing the redirect.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_DATA = tempfile.mkdtemp(prefix="mlos-test-data-")
os.environ["MLOS_DATA_DIR"] = _DATA

from app import seed  # noqa: E402  (must come after MLOS_DATA_DIR is set)

seed.seed(seed.load_modules())


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient whose notes/inbox/submissions land in tmp_path, not the repo."""
    from fastapi.testclient import TestClient

    from app import tutor, web
    from app.main import app
    from app.routes import submissions

    monkeypatch.setattr(web, "NOTES_DIR", tmp_path / "notes")
    monkeypatch.setattr(tutor, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(submissions, "ROOT", tmp_path)
    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    with TestClient(app, follow_redirects=False) as c:
        yield c
