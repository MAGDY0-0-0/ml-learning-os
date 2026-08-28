"""The library: index local PDFs into FTS5, and search arXiv / Open Library.

Local search returns page-level citations so an answer can always be traced
back to "book, page N".
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from sqlmodel import Session, select

from app.db import ROOT, raw_connection
from app.models import LibraryDoc

LIBRARY_DIR = ROOT / "library"
MIN_CHUNK_CHARS = 40


@dataclass
class Hit:
    title: str
    path: str
    page: int
    snippet: str


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def index_pdf(session: Session, path: Path) -> int:
    """Index one PDF page by page. Returns the number of pages indexed."""
    from pypdf import PdfReader

    path = Path(path)
    rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)

    reader = PdfReader(str(path))
    title = (reader.metadata.title if reader.metadata else None) or path.stem
    kind = "paper" if len(reader.pages) <= 40 else "book"

    conn = raw_connection()
    try:
        conn.execute("DELETE FROM library_chunk WHERE doc_path = ?", (rel,))
        rows = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = _clean(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - a broken page shouldn't kill the run
                continue
            if len(text) >= MIN_CHUNK_CHARS:
                rows.append((rel, title, i, text))
        conn.executemany(
            "INSERT INTO library_chunk (doc_path, title, page, text) VALUES (?,?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    doc = session.exec(select(LibraryDoc).where(LibraryDoc.path == rel)).first()
    if doc is None:
        doc = LibraryDoc(path=rel, title=title)
        session.add(doc)
    doc.title = title
    doc.kind = kind
    doc.pages = len(reader.pages)
    session.commit()
    return len(rows)


def reindex_all(session: Session) -> dict[str, int]:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, int] = {}
    for pdf in sorted(LIBRARY_DIR.rglob("*.pdf")):
        try:
            results[pdf.name] = index_pdf(session, pdf)
        except Exception as exc:  # noqa: BLE001
            results[pdf.name] = -1
            print(f"  failed to index {pdf.name}: {type(exc).__name__}: {exc}")
    return results


def search(query: str, limit: int = 20) -> list[Hit]:
    """Full-text search across indexed PDFs, newest-relevance first."""
    if not query.strip():
        return []
    conn = raw_connection()
    try:
        try:
            rows = conn.execute(
                """
                SELECT doc_path, title, page,
                       snippet(library_chunk, 3, '<mark>', '</mark>', ' … ', 24) AS snip
                FROM library_chunk
                WHERE library_chunk MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        except Exception:
            # FTS5 syntax error (unbalanced quotes etc.) -> fall back to a phrase
            safe = '"' + query.replace('"', " ") + '"'
            rows = conn.execute(
                """
                SELECT doc_path, title, page,
                       snippet(library_chunk, 3, '<mark>', '</mark>', ' … ', 24) AS snip
                FROM library_chunk
                WHERE library_chunk MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe, limit),
            ).fetchall()
    finally:
        conn.close()
    return [Hit(r["title"], r["doc_path"], r["page"], r["snip"]) for r in rows]


# --------------------------------------------------------------------------
# external lookup (both keyless)
# --------------------------------------------------------------------------


def _get(url: str, timeout: int = 20) -> str:
    """Fetch a URL via curl (works where httpx is sandbox-blocked)."""
    import subprocess

    out = subprocess.run(
        ["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", url],
        capture_output=True,
        text=True,
        timeout=timeout + 10,
    )
    return out.stdout or ""


def search_arxiv(query: str, limit: int = 8) -> list[dict[str, str]]:
    url = (
        "http://export.arxiv.org/api/query?search_query=all:"
        f"{quote_plus(query)}&start=0&max_results={limit}"
    )
    body = _get(url)
    if not body.strip():
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    out = []
    for entry in root.findall("a:entry", ns):
        title = (entry.findtext("a:title", "", ns) or "").strip().replace("\n", " ")
        link = (entry.findtext("a:id", "", ns) or "").strip()
        summary = (entry.findtext("a:summary", "", ns) or "").strip().replace("\n", " ")
        authors = [a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)]
        out.append(
            {
                "title": re.sub(r"\s+", " ", title),
                "url": link,
                "authors": ", ".join(filter(None, authors[:4])),
                "summary": summary[:400],
            }
        )
    return out


def search_openlibrary(query: str, limit: int = 8) -> list[dict[str, str]]:
    import json

    url = f"https://openlibrary.org/search.json?q={quote_plus(query)}&limit={limit}"
    body = _get(url)
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for doc in data.get("docs", [])[:limit]:
        key = doc.get("key", "")
        out.append(
            {
                "title": doc.get("title", "?"),
                "url": f"https://openlibrary.org{key}" if key else "",
                "authors": ", ".join(doc.get("author_name", [])[:3]),
                "year": str(doc.get("first_publish_year", "")),
            }
        )
    return out
