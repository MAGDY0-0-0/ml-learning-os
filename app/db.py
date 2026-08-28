"""Database engine, session helpers, and the FTS5 index for the library."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "app.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


# --------------------------------------------------------------------------
# FTS5 — kept as a raw sqlite3 table because SQLModel has no virtual-table
# support. Chunks are stored *only* here; LibraryDoc holds the metadata.
# --------------------------------------------------------------------------

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS library_chunk USING fts5(
    doc_path UNINDEXED,
    title,
    page UNINDEXED,
    text,
    tokenize = 'porter unicode61'
);
"""


def raw_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_fts() -> None:
    """Create the FTS5 table. Raises if this SQLite build lacks FTS5."""
    conn = raw_connection()
    try:
        conn.executescript(FTS_SCHEMA)
        conn.commit()
    except sqlite3.OperationalError as exc:  # pragma: no cover - env dependent
        raise RuntimeError(
            "SQLite was built without FTS5, so library search cannot work. "
            f"sqlite_version={sqlite3.sqlite_version}"
        ) from exc
    finally:
        conn.close()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    ensure_fts()
