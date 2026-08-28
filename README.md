# ML Learning OS

A local app that holds a complete ML/AI-engineer curriculum — playlists you watch
in-app, a searchable library of your own PDFs, notes, spaced repetition, progress
tracking, sandboxed assignment grading, and a rigor rubric that gates every
project.

Built in Python/FastAPI on purpose: **building this app is Module 1** of the
curriculum it contains.

## Quick start

```bash
A:\ml\run.bat
```

Then open <http://127.0.0.1:8000> and start with the [tour](http://127.0.0.1:8000/tour).

## Layout

```
app/          FastAPI application
  seed.py       curriculum/*.yaml -> DB, plus all the build-time rules
  rubric.py     Rigor Ladder + 8-type leakage checklist, and the gate
  runner.py     sandboxed pytest runner for submissions
  library.py    PDF -> FTS5 index, plus arXiv / Open Library lookup
  srs.py        SM-2 spaced repetition
  experiments.py  run logging + automatic ablation tables
  tutor.py      prompt builders; file inbox + optional model provider
curriculum/   the roadmap as YAML, and assignments with hidden tests
library/      drop your PDFs here (gitignored)
inbox/        questions and review requests for Claude Code (gitignored)
notes/        your per-unit markdown notes (gitignored)
```

## The curriculum

10 modules, 32 units, 104 resources — **every one verified reachable and free**.

| Module | Focus |
|---|---|
| M0 | Setup & Python for people who already code |
| M1 | Build this app (portfolio project 0) |
| M2 | NumPy, pandas, and the first rigor rung |
| M3 | Math recap — 2 units, no playlist |
| M4 | Classical ML + the full 8-type leakage audit |
| M5 | Deep learning + PyTorch (uses the GPU) |
| M6 | Transformers: attention → mini-transformer → nanoGPT → LoRA |
| M7 | LLM engineering, RAG, and evals |
| M8 | ML systems & MLOps |
| M9 | Portfolio: GitHub + Hugging Face + a live demo |

### Rules enforced at build time

`python -m app.seed --check` fails the build unless:

- every unit has **≥3 resources** spanning **more than one modality**, so a swap
  changes *how* you learn, not just the source;
- every unit's **primary is a video**, unless it declares `no_good_video` with a
  written reason;
- every **primary is free** (`free` or `free-audit`);
- every resource carries a **community verdict and an honest caveat**;
- every assignment has a starter file and runnable tests.

Add `--urls` to also check every link resolves.

## The Rigor Ladder

> split → leakage audit → baseline → metric → error analysis → ablation → reproducibility

Not a module — a discipline that recurs in every project and is **enforced**: a
project cannot be marked complete while any check is outstanding, and skipping
one requires a written justification that lands in `inbox/` for review.

The leakage checklist is the 8-type taxonomy from Kapoor & Narayanan,
[*Leakage and the Reproducibility Crisis in ML-based Science*](https://arxiv.org/abs/2207.07048),
which found leakage errors in 329 papers across 17 fields.

## Asking for help

Every unit, submission and rubric item has an **Ask Claude** button. It builds a
complete prompt and writes it to `inbox/`. Then tell Claude Code *"check my
inbox"*. No API key, no cost.

Optionally, put a free [Google AI Studio](https://aistudio.google.com/) key in
`.env` (see `.env.example`) to get inline answers instead.
**Never enable billing on that Google Cloud project** — the free tier disappears
entirely the moment you do.

## Tests

```bash
A:\ml\.venv\Scripts\python.exe -m pytest tests/ -q
```

Covers SM-2 against known vectors, the curriculum rules (including that the
validator actually *rejects* bad units), the rigor gate, and the two sandbox
properties that matter: an infinite-loop submission **times out** rather than
hanging the server, and submissions **cannot reach the network**.

## Environment

Python 3.13.6 · torch 2.13.0+cu130 · RTX 4060 (8 GB, sm_89) · SQLite 3.50.4 with FTS5.

GPU torch is installed separately from the app dependencies:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
```
