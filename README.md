# Magdy's ML Journey

A local web app that holds a complete machine-learning-engineering curriculum —
and enforces the engineering discipline that usually gets skipped.

Videos play inside the app, your own PDFs become searchable with page-level
citations, exercises run against hidden tests in a sandbox, and **no project can
be marked complete until it passes a data-leakage audit.**

Built with FastAPI, SQLModel and SQLite. Runs entirely on one machine — no
account, no server, no cost.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows.  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed              # load the curriculum
python -m uvicorn app.main:app --port 8000
```

Then open <http://127.0.0.1:8000>.

---

## Why it exists

Self-taught ML roadmaps fail in two predictable ways:

1. **You watch a course that doesn't suit you and blame yourself.** Here every
   unit ships at least three resources in *different formats*, so "swap" moves
   you from a video to a written explanation to something interactive — enforced
   at build time, not left to good intentions.
2. **You learn to train models but never learn to tell whether the result is
   real.** That's what the Rigor Ladder below is for.

---

## The Rigor Ladder

> split → leakage audit → baseline → metric → error analysis → ablation → reproducibility

This is not a module you finish. It recurs in every project and the app
**enforces** it: a project cannot be completed while any check is unanswered,
and skipping one demands a written justification.

The leakage audit implements the eight-type taxonomy from Kapoor & Narayanan,
[*Leakage and the Reproducibility Crisis in ML-based Science*](https://arxiv.org/abs/2207.07048),
which found these errors in **329 papers across 17 fields**:

| Code | Failure | The check |
|---|---|---|
| L1.1 | No test set | Is there a held-out set you never fit on? |
| L1.2 | Preprocessing on train+test | Were scalers/imputers fit *inside* the CV fold? |
| L1.3 | Feature selection on train+test | Was selection done without touching test? |
| L1.4 | Duplicates across splits | Deduplicated *before* splitting? |
| L2   | Illegitimate features | Is every feature available at prediction time? |
| L3.1 | Temporal leakage | Does any training row postdate a test row? |
| L3.2 | Non-independence | Same subject on both sides? (needs grouped splits) |
| L3.3 | Sampling bias | Is test drawn from the distribution you care about? |

---

## The curriculum

10 modules · 32 units · 138 resources — **every URL verified reachable, every
one free.**

| | Module | Focus |
|---|---|---|
| M0 | Setup & Python | For people who already program |
| M1 | Build this app | FastAPI, SQLModel, sandboxing — portfolio project 0 |
| M2 | Data stack | NumPy, pandas, and the first rigor rung |
| M3 | Maths recap | Two units. No playlist. Patch only what's rusty |
| M4 | Classical ML | scikit-learn + the full leakage audit |
| M5 | Deep learning | PyTorch, CNNs, ablation tables |
| M6 | Transformers | attention → mini-transformer → read nanoGPT → LoRA |
| M7 | LLM engineering | RAG, tool use, and evals as first-class code |
| M8 | ML systems | Tracking, serving, Docker, drift |
| M9 | Portfolio | GitHub + Hugging Face + a live demo |

Content is plain YAML in [`curriculum/`](curriculum/) — fork it and rewrite it
for your own path.

### Rules enforced at build time

`python -m app.seed --check` **fails the build** unless:

- every unit has **≥3 resources spanning more than one format**;
- every unit's primary is a **video**, or declares `no_good_video` with a reason;
- every primary resource is **free**;
- every resource carries an honest **verdict and caveat**;
- every exercise has a starter file and runnable tests.

Add `--urls` to verify every link still resolves.

---

## Features

| | |
|---|---|
| **Real player** | Chapters, resume-where-you-stopped, auto-logged watch time, keyboard control |
| **Video-first** | Playlists play in-app; alternates are one click away |
| **Honest resource notes** | Each shows why it's recommended *and what's wrong with it* |
| **Your own library** | Drop PDFs in `library/`; search returns the page — and opens it |
| **PDF quick-view** | A search hit opens the page in a drawer over your work, and cites into your notes |
| **Ctrl-K anywhere** | Jump to any unit, module or project without touching the mouse |
| **Sandboxed exercises** | Hidden tests, separate process, network off, hard timeout |
| **Spaced repetition** | SM-2 scheduler; the 8 leakage types are permanent cards |
| **Experiment log** | Records commit, seed and config; builds ablation tables for you |
| **Ask for help** | Writes a full-context prompt to `inbox/` for an AI assistant to answer |

---

## Project layout

```
app/
  main.py          entry point: lifespan, static mount, routers
  web.py           templates, template globals, shared view helpers
  routes/          one module per feature area
    dashboard.py   progress overview and module list
    units.py       resources, swapping, notes, asking for help
    review.py      spaced repetition
    library.py     PDF search, arXiv, Open Library
    projects.py    projects and the rigor gate
    submissions.py exercises and the test runner
    pages.py       guide and maths recap
  models.py        SQLModel tables
  db.py            engine, session, FTS5 index
  seed.py          curriculum/*.yaml -> DB, plus every build-time rule
  rubric.py        the Rigor Ladder and leakage checklist
  runner.py        sandboxed pytest runner
  library.py       PDF indexing and external search
  srs.py           SM-2 algorithm
  experiments.py   run logging and ablation tables
  tutor.py         prompt building; file inbox or optional API
  static/
    style.css      the design system: tokens, components, native motion
    app.js         command palette, toasts, background form posts
    player.js      the YouTube player: resume, chapters, auto-logging
    docview.js     the PDF quick-view drawer (pdf.js)
  templates/
    base.html      the app shell: rail, breadcrumb bar, page slot
    _icons.html    inline SVG sprite (no icon font, works offline)
    _logo.html     the mark, whose ring is live completion
curriculum/        the roadmap as YAML + exercises with hidden tests
tests/             tests for the app itself
```

---

## Tests

```bash
python -m pytest tests/ -q
```

76 tests covering the SM-2 algorithm against known vectors, the curriculum rules
(including that the validator actually *rejects* bad units), the rigor gate, and
the two sandbox properties that matter most:

- an infinite-loop submission **times out** instead of hanging the server;
- submitted code **cannot reach the network**.

---

## Notes

- **Optional AI key.** Copy `.env.example` to `.env` and add a
  [Google AI Studio](https://aistudio.google.com/) key for inline answers. Without
  one, questions are written to `inbox/` instead — no key, no cost, still works.
  Keep billing **disabled** on that project or the free tier disappears.
- **GPU.** Only modules 5–7 need one. Install PyTorch separately for your CUDA
  version — see [pytorch.org](https://pytorch.org/get-started/locally/).

## How it was built

[BUILD.md](BUILD.md) is the long version: the architecture and why it is shaped
that way, the design system, how the motion works without an animation library,
the player and PDF viewer internals, and an honest list of what is still open.

## License

MIT — see [LICENSE](LICENSE).
