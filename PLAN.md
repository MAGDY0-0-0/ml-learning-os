# Build plan for Claude Opus 5.5

Written 2026-11-12 against `master` at `c43689d`. Everything marked *measured*
or *verified* below was run that day; anything else is labelled as a judgement.

You are implementing. The planning is done, so do not re-plan — but do read the
code before each change, because line numbers drift and parts of this repo were
rebuilt recently (`app/studio.py`, `app/static/studio.css`, `app/launcher.py`,
the templates).

---

## 1. Who this is for and what they asked

Magdy is a student teaching themself ML with this app (`A:\ml`, FastAPI +
SQLModel + SQLite + Jinja, no build step). English is their second language.
They have finished two setup units and are about to start
`m0-python-idioms`. Their words for this round:

1. Fix the bugs first.
2. "When I enter each course section or slot I don't know what I am going
   into." This is the main thing to change.
3. Review the resources and use better ones where they exist.
4. Make the code more efficient.
5. Searching inside videos is **not** important. Do not build it.

Standing rules they have set, which bind you:

- **Video is their number one way of learning.** A unit's main resource is a
  video unless no good one exists. The best resource wins even if it lives off
  YouTube and cannot play inside the app.
- **Nothing ships untested.** If a feature is not working after three honest
  attempts, revert it completely and move on. No half-features in the tree.
- **Quality over quantity.** Half the work done well now, the other half later.
- **Never add a video from memory.** Every YouTube id is checked through oEmbed
  and every timestamp comes from `python -m scripts.chapters <id>`.
- Commit only when asked. Never push or open a PR without Magdy saying so.

## 2. Things that will hurt you if you do not know them

- **`data/app.db` is Magdy's real progress.** `m0-env` and `m0-git` must stay
  `done`. Copy the file somewhere safe before any reseed. The test suite is
  safe: `tests/conftest.py` points the app at a temp directory.
- **Reseed with** `.venv/Scripts/python.exe -m app.seed`. Seeding keys resources
  by URL within a unit, so changing a URL deletes the old row and its watch
  position (`app/seed.py`, the `stale` loop). No resource has a saved position
  today, so nothing is lost by the changes below.
- **Edit the YAML by hand, matching the sibling lines.** Each file has its own
  indentation and line endings (`m7_llm.yaml` is CRLF). Never round-trip a file
  through a YAML dumper. In `m4`–`m7` and `m9` there is a top-level `projects:`
  key after `units:`; a unit pasted below it becomes a project and silently
  does nothing.
- **Port 8000 is fixed** (`m3_math.yaml` links to `http://127.0.0.1:8000/recap`).
  Start the app with the preview tool using the `ml-journey` launch config. If
  the port is busy it is usually a leftover server from an earlier session.
- **The Browser pane may be hidden**, and then screenshots time out and anything
  that waits on `requestAnimationFrame` can stall. Verify with `read_page`,
  `get_page_text` and `javascript_tool`, or ask Magdy to show the pane.
- **Write multi-line scripts with the Write tool**, not through a heredoc with
  escapes. Earlier sessions lost time to mangled `\n`.

Commands you will run constantly:

```bash
.venv/Scripts/python.exe -m app.seed --check          # curriculum rules, offline
.venv/Scripts/python.exe -m app.seed --check --urls   # plus every link, needs network
.venv/Scripts/python.exe -m pytest tests -q           # 180 tests, about 80 s today
```

## 3. What to build, in two stages

**Stage A is this job.** Stage B waits until Magdy asks for it.

| | Stage A (now) | Stage B (later) |
|---|---|---|
| Phase 1 | All fixes | — |
| Phase 2 | The briefing, for every module and unit | — |
| Phase 3 | Named videos and better resources for M0–M4, plus the one M5 unit that is badly mislabelled | M5–M9 |
| Phase 4 | The `/projects` fix and the statement-budget test | The smaller query trims |

Work in this order. One branch per phase off `master`
(`fix/first`, `feat/briefing`, `content/named-videos`, `perf/queries`).

---

## Phase 1 — Fix first

### 1.1 Scheduled CI is red for a link that is not dead

*Measured:* the weekly `links` job fails with
`m8-serving: HTTP 403 for https://madewithml.com/`. The same URL returns 200
from this machine. GitHub's runners are being refused; the page is fine.

*Cause:* `app/seed.py` `_check_one` treats a 403 or 429 as a failure unless the
host is in `BOT_BLOCKING_HOSTS`. That list can only ever be behind.

*Change:* a 403 or 429 from a non-oEmbed host means "could not verify", for any
host. Print it as a warning with a count at the end, and do not add it to
`errors`. Keep failing on 404, 410, 5xx, `000` and oEmbed failures — those are
the answers that mean a link is really gone. Retry a 403 once with a full
browser User-Agent before settling (the current one is the bare string
`Mozilla/5.0`). Delete `BOT_BLOCKING_HOSTS` once nothing reads it.

*Done when:* a unit test drives `_check_one` with `_fetch_status` monkeypatched
(403 on an unknown host → no error; 404 → error; oEmbed 400 → error), and
`--check --urls` exits 0 locally.

### 1.2 The time gate trusts the number it is supposed to check

*Measured:* `m5-training-loop`'s main video
(`V_xro1bcAuA`) is **25 h 37 min**. The YAML says 120 min, so the gate that
compares resource length to unit length never fires. Thirteen other resources
are also wrong:

| Unit | Video id | Claimed | Real |
|---|---|---|---|
| m5-training-loop (main) | `V_xro1bcAuA` | 120 | 1537 |
| m5-training-loop | `Z_ikDlimN6A` | 120 | 1536 |
| m7-rag | `qN_2fnOPY-M` | 120 | 340 |
| m2-pandas | `gtjxAH8uaP0` | 100 | 297 |
| m0-python-idioms | `rfscVS0vtbw` | 90 | 266 |
| m1-fastapi-basics | `VirndPTeRaw` | 120 | 203 |
| m1-sandboxing | `YbpKMIUjvK8` | 15 | 35 |
| m2-numpy | `uaTigVkG2dk` | 60 | 77 |
| m8-tracking | `_Ox2Ft0xumE` | 180 | 134 |
| m8-tracking | `kn51WgTTjCw` | 45 | 25 |
| m9-deploy-demo | `eE7CamOE-PA` | 35 | 13 |
| m1-sqlmodel | `z_Xl_vT06wg` | 35 | 24 |
| m1-fastapi-basics | `SORiTsvnU28` | 30 | 20 |
| m0-env | `N5vscPTWKOk` | 16 | 9 |

*Change:*

1. In the `--urls` pass, for every single YouTube video read the real length
   from the watch page (`"lengthSeconds":"N"`, fetched the way
   `scripts/chapters.py` already fetches chapters) and fail when the claimed
   `est_minutes` is off by more than `max(5, 20%)`. If the length cannot be
   read (YouTube sometimes serves a consent page to data-centre IPs), warn and
   do not fail.
2. In the same pass, check every `watch[].video` id through oEmbed and check
   that each `to` is not past the end of the video. Today only the resource
   URL is checked, so a segment can point at a dead video.
3. Correct the fourteen values above.
4. Correcting `m5-training-loop` will trip the existing gate, which is right.
   Give it this segment, taken from the video's own chapters (*verified*):
   `from: "5:41:15"`, `to: "7:15:53"` — chapters 43 to 49, "Training a model
   with PyTorch (intuition building)" through "Writing testing loop code",
   95 min. Run `python -m scripts.chapters V_xro1bcAuA` to confirm before
   writing it.
5. Give `scripts/chapters.py` a line that prints the video's total length. It
   currently infers the end from the last chapter, which fails on videos with
   one chapter or none.

*Done when:* `--check --urls` passes, and a test proves a 25-hour video
claimed as 120 minutes is rejected.

### 1.3 The PDF drawer: not broken today, but fragile

`BUILD.md` §13 records `page.render()` hanging forever. *Measured today:* the
drawer opened page 101 of a 1,151-page book in 2.1 s and turned the page
correctly. The stall did not reproduce.

*My best explanation, not proven:* pdf.js schedules on-screen rendering with
`requestAnimationFrame`, which browsers pause in a background tab, and the
earlier tests ran in a hidden Browser pane. That fits every row of the table in
§13 (document and page load, render never settles, no error).

Two real weaknesses remain in `app/static/docview.js`, and both are worth
fixing:

- **A lock that can stick and a page counter that can drift.** `render()`
  returns early while `rendering` is true, but `go()` has already changed
  `page`. Press Next twice quickly and the label, the canvas and the counter
  disagree; if a render never settles the drawer is dead until reload. Replace
  the boolean with the render task itself: keep the `RenderTask`, cancel it
  when a new page is requested, ignore `RenderingCancelledException`, and only
  swap the canvas in if the finished page is still the wanted one.
- **It needs the network.** pdf.js and its worker load from cdnjs on first
  open. This is the app's last external request. Vendor `pdf.min.js` and
  `pdf.worker.min.js` version **3.11.174** into `app/static/vendor/pdfjs/` and
  point `workerSrc` at the local file. Stay on 3.x: 4.x and later ship ES
  modules only and an upgrade was tried and reverted (§13). Downloading the
  two files needs Magdy's OK — ask once, with file names, source and size.

*Done when:* with the pane visible, opening a PDF makes no request to
`cdnjs.cloudflare.com`; pressing Next five times quickly lands exactly five
pages on, with label and canvas agreeing. Then rewrite the PDF section of
`BUILD.md` §13 to say what was found, and delete the stale bullet there that
says tests share the learner's database (they no longer do).

### 1.4 Routes that create rows for things that do not exist

In `app/routes/units.py`:

- `append_notes` writes `notes/<slug>.md` for any slug. `save_notes`, one
  screen above it, checks the unit exists. Add the same check.
- `save_position`, `set_watched` and `toggle_resource` create a
  `ResourceState` for any integer. That is how the phantom "Resumes at 1:23"
  bug happened before. Return `{"ok": False}` when `s.get(Resource, rid)` is
  `None`.

*Done when:* tests post to a made-up slug and a made-up resource id and assert
no file and no row.

### 1.5 A unit lost its "done" state

*Found today:* `m0-env` was `not_started` in the real database although
`notes/m0-env.md` records it being marked complete. `m0-git` was `done` with a
`completed_at` of 2026-10-23, not the original September date, so progress was
rebuilt that day and one row was missed. **I have already restored it** (backup
taken first). Your part: spend at most twenty minutes finding which path
dropped it (start with `app/backup.py` `import_state` and the tests around
it), and add a test that a full export → fresh seed → import returns every
unit's status unchanged. If you cannot find the cause, say so plainly.

### 1.6 Small, only if the above went smoothly

- **Tests are slow to iterate on.** *Measured:* 180 tests in 80 s; five tests
  in `tests/test_launcher.py` take 37 s of that. Add a `pytest.ini`, register
  a `slow` marker, mark those five and the 5 s runner-timeout test. CI keeps
  running everything; use `-m "not slow"` in your own loop.
- **Eight resources name "YouTube" as their teacher** (`YouTube (2025)`,
  `YouTube (Oct 2025)` and so on, in `m1`, `m5`, `m7`, `m8`). Replace each with
  the channel name oEmbed returns, and make the gate reject a `provider` that
  starts with `YouTube`.
- **`Resource.verified_at` and `reviewed_at` are never written.** The model
  says `--urls` writes one and the YAML supplies the other; neither happens
  and no template shows them. Have `seed()` copy `reviewed_at` from the YAML,
  and have `python -m app.seed --urls` (without `--check`) stamp `verified_at`
  on each link that answered. Showing them on the page is Stage B.

---

## Phase 2 — Know what you are walking into

### What is wrong

*Measured on the page Magdy opens next,* `/unit/m0-python-idioms`: a title, one
sentence, then a player for a **158-video playlist** labelled "about 1 h". The
card that says what to watch starts at y=736 in a 768-pixel window, so it is
below the fold. Nothing says what they will be able to do afterwards, how the
time splits between watching and practising, or whether they can skip it.

The module page lists units with a sentence each and chips such as
"2 videos · 4 resources". Those chips count the alternates, not what you will
actually do. There is no total time, no outcome, no "start here".

The tiles on Today show a title and a number of minutes.

### What to build

One idea, shown at three sizes: **the briefing**. Before the work starts, say
why it matters, what you will be able to do, exactly what you will do and for
how long, and when you may skip it.

**New authored fields** (YAML → database):

```yaml
# on a unit
why: One sentence. Where this gets used later, in plain words.       # required
outcomes:                                                            # required, 2 to 4
  - Starts with a verb. Something you can be asked to do in five minutes.
needs: [m0-python-idioms]     # optional: unit slugs that must come first
skip_if: One sentence.        # optional: who can go straight to the checks

# on a module
outcomes: [ ... ]             # required, 3 to 5
```

Store them as `Unit.why`, `Unit.outcomes_json`, `Unit.needs_json`,
`Unit.skip_if`, `Module.outcomes_json`. Add each to `ADDED_COLUMNS` in
`app/db.py` with a default — that tuple is the migration mechanism here, and
without it an existing database fails with "no such column".

**Everything else in the briefing is derived, never authored.** Write one
helper in `app/studio.py`, next to `practice_status`, that returns for a unit:

- the watch plan: each `watch` segment's title and minutes, or the main
  resource's title and minutes when there are no segments;
- the exercises with their check counts (reuse `practice_status`);
- the number of checkpoint questions and review cards;
- each `needs` unit with whether it is done;
- the project this module unlocks and how many units away it is (the dashboard
  route already computes this; move that logic somewhere both can use).

Write a second helper that does the same for a whole module in a fixed number
of queries, because the module page would otherwise run the unit helper once
per row.

**Gate rules** (`app/seed.py`, with tests beside the existing
`test_validator_catches_*` in `tests/test_app.py`): a unit without `why` fails;
`outcomes` must have 2 to 4 entries of at most 90 characters; a module needs 3
to 5; every slug in `needs` must exist and come earlier in the curriculum. The
rule and the content for all 33 units and 10 modules land in the same commit,
or CI goes red.

### Where it shows

**Unit page** (`app/templates/unit.html`, inside `#learn`, after the objective
and above the player). A `<details class="brief">`, open on a first visit and
closed once the unit has logged minutes or a saved position — decide that on
the server, no script. Contents in this order:

1. `why`.
2. "By the end you can" — the outcomes.
3. "What you'll do" — a short numbered list with minutes: watch (each named
   part), practise (exercise name, number of checks), check (number of
   questions). The minutes must add up to the unit's `est_minutes`.
4. "First" — the `needs` units as links with a tick when done. Omit if empty.
5. "Already know this?" — `skip_if`, and a link that jumps to the Finish step.
   Completion already requires every checkpoint to be attempted, so this is an
   honest way to test out, not a bypass. Omit if the unit has no checkpoint.

On a wide screen put outcomes and "what you'll do" side by side so the open
briefing stays under about 220 px and the player is still on the first screen.
Closed, it is one line.

**Module page** (`app/templates/module.html`, route in
`app/routes/dashboard.py`). Add to the header: "After this module you can" with
the outcomes; one line of real totals (units, hours, exercises, checks); a
Start or Continue button to the first unit not yet done; the project it
unlocks. In each row replace the `N videos · N resources` chips with what the
row asks of you: `Watch 70 min`, `1 exercise`, `3 checks`. Show `why` under the
title in place of the objective.

**Today** (`app/templates/dashboard.html`). Add the same compact line to the
hero's meta row and under each poster's title. On the module tiles in "The
road ahead" show units and total time (`3 units · 6 h`) instead of units alone.

Reuse what `studio.css` already has (`.side-card`, `.chip`, `.kick2`, the
`data-phase` colours). No new colours, no new fonts, no JavaScript.

### How to write the text

This is the part that decides whether the feature is any good.

- An outcome is something Magdy could be asked to do in five minutes and would
  either manage or not. "Write a list comprehension with a filter" passes.
  "Understand comprehensions" fails.
- Promise only what the unit's main resource and exercise really cover. Check
  the video's chapter list before you write, and read the exercise's tests.
- Plain English. Short sentences. No idioms and no jokes that depend on
  culture. Explain a term the first time it appears.
- `why` names the later unit or project where the skill is used, when there is
  one.

A worked example to match in tone:

```yaml
- slug: m0-python-idioms
  why: NumPy, pandas and PyTorch code is full of slices, comprehensions and
    unpacking. Until these are automatic, every later video reads like noise.
  outcomes:
    - Replace a for-loop that builds a list with a comprehension, with a filter
    - Slice a list or string with start, stop and step, including negatives
    - Unpack a tuple in an assignment and in a for-loop
    - Say which values count as false in an if, and format text with an f-string
  skip_if: You can write [x*x for x in xs if x % 2] and xs[::-1] without
    looking anything up. Go straight to the drill and the checks.
```

### Done when

- Opening any unit for the first time shows the briefing above the player, and
  `get_page_text` on three different units reads as a sensible answer to "what
  am I about to do?".
- The minutes in "what you'll do" add up to the unit's total on every unit
  (write this as a test over the seeded curriculum, not a spot check).
- The module page shows outcomes, real totals and a working Start button.
- Tests cover: the helper's derived values; the page with and without
  segments, exercises and checkpoints; the closed state after progress; the
  four gate rules.
- Checked at phone width (375) as well as desktop.

---

## Phase 3 — Say exactly what to watch, and use the best thing

### The problem

*Measured:* in 17 of 33 units the main resource is a whole playlist with no
video named. Several are huge, and several do not teach what the unit says:

| Unit | Main resource today | Videos in it |
|---|---|---|
| m0-python-idioms | Corey Schafer, Python Tutorials | 158 |
| m4-sklearn-api | StatQuest, Machine Learning | 106 |
| m4-models | sentdex, Machine Learning with Python | 72 |
| m6-finetune-lora, m7-apis-prompting, m9-deploy-demo | Hugging Face Course | 80 |
| m8-tracking, m8-monitoring, m9-interview | MLOps Zoomcamp | 43 |
| m5-cnns | Andrew Ng, CNN course | 42 |
| m5-backprop, m6-attention, m6-architecture, m6-mini-transformer | 3Blue1Brown / Zero to Hero | 10 |
| m2-pandas | Corey Schafer, Pandas | 11 |
| m0-oop-dunders | Corey Schafer, OOP | 6 |
| m3-gap-patch | 3Blue1Brown, Calculus (look-up only) | 12 |

This is the same complaint as Phase 2 from the content side: a briefing cannot
say "watch these four videos" if the curriculum does not know which four.

### The rules to add

1. A main resource whose URL is a playlist (detect by URL: `list=` with no
   `v=`; `kind` is not reliable here) must have a `watch` block naming each
   video, or `lookup_only: true`, or a new `whole_playlist: true` for a short
   series that really is watched end to end. In the `--urls` pass, reject
   `whole_playlist` on a playlist of more than 12 videos.
2. A unit's `est_minutes` is watching plus practice. Enforce
   `est_minutes ≥ selected watch minutes + 20 × number of exercises`, and
   raise the unit's number where it fails. An honest 110 is better than a
   comfortable 70.

Read `app/static/player.js` before choosing how to express a multi-video unit.
Segments already chain by video id inside a playlist. Where the videos you
want are not all in one playlist, make the resource URL the first video and
check that the player moves to the next id; if it does not, that is a player
fix with its own test.

Stage A enforces rule 1 for M0–M4 only. Do that with a short, commented
allow-list of the M5–M9 unit slugs still to do, so the gap is visible in the
code and shrinks to nothing in Stage B.

### Stage A: unit by unit

Every id below was *verified* through oEmbed today, with real lengths. Whether
a video is the best teacher for the unit is my judgement from knowing these
videos and reading their chapter lists; nobody watched them this session, so
leave `reviewed_at` empty. Before writing a segment, run
`python -m scripts.chapters <id>`.

| Unit | Change | Verified facts |
|---|---|---|
| **m0-python-idioms** | Name four Corey Schafer videos instead of the playlist: Comprehensions, Slicing, F-Strings, and Lists/Tuples/Sets (for unpacking). Find his "Conditionals and Booleans" video for truthiness by listing the playlist; I did not verify an id for it. Add mCoding's video as an alternate: it is aimed at people arriving from other languages. Raise `est_minutes` to cover the drill. | `3dt4OGnU5sM` 18 min · `ajrtAuDg3yw` 10 · `nghuHvKLhJA` 13 · `W8KRzm-HUcc` 29 · alternate `qUeud6DvOWI` 9 |
| **m0-oop-dunders** | `whole_playlist: true`. Measure the six videos and correct the 75. | 6 videos |
| **m2-pandas** | Promote Keith Galli's 2025 edition to main if its chapters cover merging: the unit promises joins and Corey Schafer's 11-part series has no video on them. Keep Corey as the slower, deeper alternate with named parts. | `2uvysYbKdjM` 94 min, 30 chapters, published 2024-06 |
| **m4-sklearn-api** | Replace the StatQuest playlist, which explains algorithms and does not teach the scikit-learn API. Main becomes freeCodeCamp's scikit-learn crash course, segmented to fit. Add the Inria scikit-learn course, written by the library's own developers, as an alternate. Keep StatQuest as a concept alternate with named videos. | `0B5eIE_1vpU` 129 min, 7 chapters · `https://inria.github.io/scikit-learn-mooc/` 200 |
| **m4-models** | Replace sentdex: it is from 2016 and builds KNN and SVM from scratch, while the unit is trees, forests and boosting. Main becomes four named StatQuest videos, 67 min, leaving the rest of the 150 for hands-on work in the `handson-ml3` notebooks already listed. | `_L39rN6gz7Y` 18 · `J4Wdy0Wc_xQ` 9 · `3CC4N4z3GJc` 15 · `OtD8wVaFm6E` 25 |
| **m4-leakage-audit** | The alternate "StatQuest — cross validation chapters" is the same 106-video playlist. Point it at the one video. | `fSytzGwwBVw` 6 min |
| **m5-training-loop** | The segment from Phase 1.2. Add Karpathy's makemore part 3 as an alternate for the "model that won't learn" half, with the caveat that it assumes parts 1 and 2. | `P6sfmUTpUmc` 115 min, 17 chapters |

`m3-gap-patch` and `m3-recap-sheet` are look-up lists by design: mark the
playlist entries `lookup_only: true` and leave them.

### Stage B: notes for later, so the research is not lost

Do not do these now. Ids are verified; fit is my judgement.

| Unit | Direction |
|---|---|
| m5-backprop | Name the micrograd lecture, `VMj-3S1tku0`, 145 min. |
| m5-cnns | Name the week-1 videos of Ng's course. Add Stanford CS231n Spring 2025 lectures 5 and 6 as the current alternate (playlist `PLoROMvodv4rOmsNzYBMe0gJY2XS8AQg16`). |
| m6-attention | 3Blue1Brown chapters 5 and 6: `wjZofJX0v4M` 27 min, `eMlx5fFNoYc` 26 min. |
| m6-architecture | "Let's build GPT", `kCc8FmEb1nY`, 116 min. Matches the unit's 116 exactly. |
| m6-mini-transformer | The "makemore series" is not about transformers. Consider Umar Jamil's code-along, `ISNdQcPhsts`, 179 min, segmented to the building blocks. |
| m6-nanogpt-read | Marked "no good video", but Karpathy's "Let's reproduce GPT-2", `l8pRSuU81PU`, writes the same model file line by line. Use only its first section, to respect the module's rule against reproducing GPT-2. |
| m6-finetune-lora | The Hugging Face videos are from 2021 and have no LoRA. Use Shaw Talebi's two videos, `eC6Hd1hFvos` 28 min and `XpoKB3usmKc` 36 min, and point the course alternate at chapter 11, `https://huggingface.co/learn/llm-course/chapter11/1`, which now covers LoRA. Unsloth's docs suit an 8 GB card. |
| m7-apis-prompting | The Hugging Face playlist does not teach model APIs. Candidate main: Anthropic Academy, "Building with the Claude API" (`https://anthropic.skilljar.com/claude-with-the-anthropic-api`). Confirm it is free before using it. The "Structured outputs" alternate links to an unrelated docs index. |
| m7-rag | The main link opens chapter 1 of a course, not RAG. Daniel Bourke's local RAG, `qN_2fnOPY-M`, 340 min with 31 chapters, runs on a local GPU with no framework and is the closest match to Project 4. Segment it. Add Anthropic's "Contextual retrieval" article. |
| m7-evals | Marked "no good video"; there is one now. Hamel Husain and Shreya Shankar's walkthrough, `BsWxPI9UM4c`, 106 min, 25 chapters, includes error analysis on real traces. Add `https://hamel.dev/blog/posts/evals-faq/` and `https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents`. |
| m8-tracking, m8-monitoring | Name the Zoomcamp module 2 and module 5 videos. |
| m8-serving | The Docker course is from 2019. TechWorld with Nana's is shorter and newer: `pg19Z8LL06w`, 67 min. I found no verified video that covers serving a model with FastAPI and Docker together. |
| m9-deploy-demo | Name the Spaces and Gradio videos. |
| m9-interview | "MLOps Zoomcamp design modules" do not exist. I found no free video series worth making the main resource. Honest option: `no_good_video` with Chip Huyen's free booklet, `https://huyenchip.com/machine-learning-systems-design/toc.html`. |

### Done when (Stage A)

- `--check` and `--check --urls` pass with the new rules.
- No M0–M4 unit's main resource is an unnamed playlist.
- For each changed unit, the briefing from Phase 2 lists real video titles
  with real minutes, and the player starts on the first named video.
- You report which swaps still need a person to watch them.

---

## Phase 4 — Efficiency

*Measured, median of seven loads:*

| Page | Time | SQL statements |
|---|---|---|
| `/projects` | 44 ms | **99** |
| `/` | 16 ms | 20 |
| `/unit/…` | 18 ms | 19–20 |
| everything else | 8–18 ms | 3–21 |

The app is already fast. There is one real defect and one guard worth adding.

**4.1 `/projects`.** `rubric.ensure_checks` calls `session.commit()` on every
call, even when it added nothing. A commit expires every loaded object, so each
later attribute read reloads one row at a time. Commit only when a check was
actually created, and load all `RubricCheck` rows for the page in one query.
Target: 12 statements or fewer.

**4.2 A statement budget.** Add a test that counts statements with a
`before_cursor_execute` listener on `app.db.engine` and fails when a page goes
over its budget: `/projects` 12, `/` 22, a unit page 22, a module page 12.
Phase 2 adds queries to three of these pages; this test is what keeps that
honest. Write it before Phase 2 if that is convenient.

**Stage B, small:** `due_count` in `app/web.py` and the two sums in the
dashboard route load whole tables to count in Python; the module route runs
one resource query per unit; `studio.next_unit` runs one query per module.
Each is a few milliseconds. Fix them only together with the budget test, and
keep the datetime comparison semantics exactly as they are.

---

## 4. Deliberately not in this plan

- **Search inside videos or transcripts.** Magdy said it is not important.
- **Search by meaning (embeddings).** It is Project 4 of their own curriculum;
  building it for them would do their portfolio project.
- **A new flashcard scheduler (FSRS).** No card has been reviewed yet, and the
  M1 exercise has the learner implement SM-2 against `app/srs.py`.
- **A frontend framework, a vector database, async database code.** Pages
  render in under 20 ms.
- **Better Ctrl-K search** (typo tolerance, notes and PDFs in one box). Worth
  doing one day; not asked for now.

## 5. What to send back after each phase

A short report Magdy can read without the code open: what changed and where;
the test run's last line; before and after numbers where the phase has them
(statements, minutes, link-check result); anything you reverted under the
three-attempt rule and why; and the decisions you need from them. State
plainly what you verified and what you only inferred.

Decisions that are Magdy's, not yours:

1. Permission to download the two pdf.js files (Phase 1.3).
2. Whether to push. Local `master` is two commits ahead of `origin/master`
   before you start.
3. Any Stage B item, and any resource you think should be main but could not
   confirm is free.
