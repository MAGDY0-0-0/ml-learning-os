"""Ask-for-help plumbing.

Two paths, and the file path always works:

1. **File inbox** (no key, no cost). Builds a fully-formed prompt and writes it
   to inbox/. Claude Code reads those files directly — say "check my inbox".
2. **API** (optional). If a provider key is present in .env, the same prompt can
   be answered inline. Gemini is the default because its free tier costs
   nothing, PROVIDED billing stays disabled on the Google Cloud project.

Never commit .env — it is gitignored.
"""

from __future__ import annotations

import os

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.db import ROOT

INBOX = ROOT / "inbox"


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()


@dataclass
class Provider:
    name: str
    available: bool
    note: str


def provider_status() -> Provider:
    """Which backend would answer inline, if any."""
    if os.environ.get("GEMINI_API_KEY"):
        return Provider("gemini", True, "Gemini free tier (Flash models; keep billing DISABLED)")
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Provider("anthropic", True, "Anthropic API")
    if os.environ.get("OPENAI_API_KEY"):
        return Provider("openai", True, "OpenAI API")
    return Provider(
        "inbox",
        False,
        "No API key set — questions are written to inbox/ for Claude Code to read.",
    )


def write_inbox(kind: str, title: str, body: str) -> Path:
    """Write a prompt to inbox/ and return the path."""
    INBOX.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in title.lower())[:50]
    path = INBOX / f"{kind}-{stamp}-{safe}.md"
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# prompt builders
# --------------------------------------------------------------------------


# NOTE: these are written flush-left on purpose. textwrap.dedent cannot strip a
# common indent once multi-line values (code, notes, test output) have been
# interpolated, because those lines carry no indent of their own.

def unit_help_prompt(
    unit_title: str,
    objective: str,
    resource_title: str,
    notes: str,
    question: str,
) -> str:
    return f"""# Help request — unit: {unit_title}

**Unit objective**
{objective.strip() or "(none recorded)"}

**Resource I'm stuck on**
{resource_title or "(none selected)"}

**My notes so far**
{notes.strip() or "(empty)"}

**My question**
{question.strip()}

---
Please explain this at the level of someone who can program but is new to Python
and ML. Prefer a concrete example over an abstract definition, and tell me if my
question itself is based on a misunderstanding.
"""


def review_prompt(
    assignment_title: str,
    brief: str,
    code: str,
    test_output: str,
    passed: int,
    total: int,
) -> str:
    return f"""# Code review request — {assignment_title}

**Assignment brief**
{brief.strip()}

**Result:** {passed}/{total} hidden tests passing

**My code**
```python
{code.strip()}
```

**Test output**
```
{test_output.strip()[:4000]}
```

---
Please review for correctness, then for style and idiom. Point out anything that
would fail on an edge case the tests don't cover. If the approach itself is
wrong, say so directly rather than polishing it.
"""


def rubric_skip_prompt(project_title: str, code: str, label: str, justification: str) -> str:
    return f"""# Rubric skip — {project_title}

I skipped rigor check **{code} — {label}**.

**My justification**
{justification.strip()}

---
Push back on this if the justification doesn't hold. Skipping a leakage check is
sometimes legitimate (e.g. L3.1 on non-temporal data) and sometimes
self-deception — tell me honestly which this is.
"""


# --------------------------------------------------------------------------
# optional inline answering
# --------------------------------------------------------------------------


def ask_inline(prompt: str) -> str | None:
    """Answer via an API if one is configured, else None.

    Degrades to None on any failure (including rate limits) so the caller falls
    back to the inbox rather than surfacing an error.
    """
    prov = provider_status()
    if not prov.available:
        return None
    try:
        if prov.name == "gemini":
            import google.generativeai as genai

            genai.configure(api_key=os.environ["GEMINI_API_KEY"])
            # Free tier covers Flash models only.
            model = genai.GenerativeModel(
                os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            )
            return model.generate_content(prompt).text
        if prov.name == "anthropic":
            import anthropic

            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            msg = client.messages.create(
                model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in msg.content if hasattr(b, "text"))
    except Exception as exc:  # noqa: BLE001
        print(f"[tutor] inline answer failed ({type(exc).__name__}); using inbox")
        return None
    return None
