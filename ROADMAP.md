# Roadmap: the next versions

Written 2026-11-20 against `master` after "Make a finished unit read as
finished". This is a plan only. Nothing here is built yet.

Who builds it: a top model plans, Claude Opus implements (see `PLAN.md` for
how the last plan was written and followed). Each version below is small
enough to finish, test and push on its own.

---

## Where the app stands (measured 2026-11-20)

What is strong:

- 10 modules, 33 units, 154 resources. Every unit opens with a briefing (why,
  outcomes, timed plan, needs, skip-if) and names exactly which videos or
  minutes to watch. The build gate enforces all of it.
- The player plays named parts as clips and resumes where you stopped. The PDF
  drawer works offline. Pages run 4–20 SQL statements, capped by tests.
- About 260 tests; CI is green on Linux and Windows, plus a weekly link check.

What is weak, from the curriculum and the real database:

| Measured | Number | Why it matters |
|---|---|---|
| Units with checkpoint questions | **7 of 33** | 26 units are "watch, then mark done", with no check that anything stuck |
| Units with a coded exercise | **7 of 33** | M3, M8 and M9 have none; M5 and M6 have one each |
| Review cards | **60**, 0–5 per unit | Spaced repetition only works with steady input |
| Study sessions logged | **0** | The app has not been used for real study yet |
| Videos reviewed by a person | **0** | All checked by script only |
| Units done | **2 of 33** | |

The most important row is "study sessions logged: 0". The app is ready to
learn from. Its next improvements should come from real use, not guesses.
So version 1.1 starts with a way to record problems as they happen.

---

## Rules for every version

These carry over from the last plan and still bind:

1. **Fix before adding.** Any bug found in use goes first.
2. **Tested or removed.** Each feature ships with tests. If it still does not
   work after three honest attempts, revert it fully and move on.
3. **Videos first.** Never add a video id from memory: verify with oEmbed, take
   times from `python -m scripts.chapters <id>`, and run
   `python -m app.seed --check --urls`.
4. **The learner's data is real.** Back up `data/app.db` before any reseed.
   Browser tests write to the real database, so clean up what they wrote.
5. **Plain English** in every label and message. The learner reads English as a
   second language.
6. **Push only when asked.**

---

## v1.1: Use it, and catch problems as they happen

**Goal:** study for two weeks, with a one-click way to note anything that is
wrong or confusing.

1. **"Something's off here" button** on every unit, module and project page.
   It opens a small box (one line, optional) and appends to
   `feedback/YYYY-MM.md`: date, page URL, unit slug, current video and second
   (if the player is open), and the text. No network, no AI.
   - Done when: a test posts feedback and finds the line in the file, and
     `feedback/` is added to `.gitignore` next to `notes/`.
2. **Check that watch time is really logged.** `studysession` has 0 rows,
   which may only mean nobody has studied yet. After the first real session,
   confirm rows appear in `studysession` and `resourcestate`. If they do not,
   that is a bug and goes first.
3. **A first-week summary on Today**: minutes this week, units touched, cards
   reviewed. All three already exist in the database; this only shows them.
   - Done when: the numbers match a hand count in the database, and Today
     stays within its statement budget (22).

**Not in v1.1:** anything bigger. The point is to learn and collect notes.

---

## v1.2: Practice in every unit

**Goal:** no unit ends with "watch and mark done". This is the biggest gap in
the app.

1. **Checkpoint questions for the 26 units without them.** 2–3 questions each,
   written from the named video parts so each answer is in what was watched.
   Then add a gate rule: every unit needs at least 2 checkpoints, except
   setup units that declare `no_checkpoint: <reason>` (`m0-env`, `m0-git`).
   - Write them module by module (M1 first, then M3, M4, …), one commit per
     module, and run `--check` after each.
   - Keep the settled rules in `CheckpointAnswer` (`app/models.py`): you
     reveal the answer and mark yourself; "attempted" gates completion,
     "I knew it" does not. A question marked not known already becomes a
     review card due now, so these new questions feed review for free.
2. **At least 3 review cards per unit.** Today it is 0–5. Cards should test one
   fact or one decision each ("When do you use a grouped split?"), not
   definitions copied from the video. Gate rule: `cards ≥ 3` per unit.
3. **Six new coded exercises**, where writing code is the skill:

   | Unit | Exercise | Tests check |
   |---|---|---|
   | `m2-numpy` | vectorise three loops | same output, no Python loops over rows |
   | `m3-recap-sheet` | gradient of 3 functions, by hand in code | numeric gradient matches |
   | `m5-backprop` | a tiny autograd `Value` class (micrograd-style) | `+ * tanh` and backward match finite differences |
   | `m5-training-loop` | fill in train/eval loop | loss falls on a toy set; `model.eval()` and `no_grad` used |
   | `m7-evals` | score a fixed set of answers with a rubric | exact counts on a frozen file, no API call |
   | `m8-serving` | a FastAPI `/predict` with input checks | 200 on good input, 422 on bad |

   - Read `app/runner.py` first: submissions run with no network and a
     timeout. Exercises that need `torch` must say so and be skipped with a
     clear message (not failed) when `torch` is missing, so CI stays green.
   - Each exercise needs a starter file, hidden tests, and a reference
     solution that passes them (kept out of the starter).

**Done when:** `--check` passes with the new rules, every new exercise's
reference solution passes its own tests in the sandbox, and the starter
fails them.

---

## v1.3: Close the learning loop

**Goal:** what you get wrong comes back to you.

1. (Already built: a checkpoint you mark as not known becomes a card due
   now. v1.2 gives it 26 more units' worth of questions to work with.)
2. **Make a card from your notes.** A small "+ card" next to the notes box:
   select text, write a question, save. Cards made this way belong to the unit.
3. **A study plan with a finish date.** A setting for hours per week (default
   6). Today shows: "At 6 h a week you finish M2 around 12 Dec and the whole
   path around …", computed from the remaining units' `est_minutes`. Pure
   arithmetic, no AI.
   - Done when: a unit test checks the date for a fixed "today" and a fixed
     set of done units.
4. **Review reminder on the launcher.** When the app opens and cards are due,
   Today shows the count first. (No system notifications: they need
   permissions and are easy to get wrong on Windows.)

---

## v1.4: Trust the content

**Goal:** every recommended video has been watched by a person.

1. **Rate a resource after finishing it**: three buttons, "Great", "OK",
   "Not for me", plus an optional line. Stored in the database (new table
   `ResourceRating`), shown on the resource as "you rated this …".
2. **Reviewed date from real use.** When a resource is rated, the page shows
   "reviewed by you on …". `python -m app.seed --report-ratings` prints the
   ratings so a person can copy `reviewed_at` and any changed `verdict` into
   the YAML by hand. The YAML stays the source; nothing rewrites it
   automatically.
3. **"Not for me" moves the resource down** the same way swapping does today
   (swap preferences already exist in `routes/units.py`).
4. **Weekly link check also checks length drift.** If a video got shorter or
   longer by more than the allowed amount, the scheduled CI run fails with the
   unit name, so a re-cut video is noticed.

---

## v1.5: Small quality work

Do these only after v1.1–v1.4, and only those that still matter by then:

- **Phone and narrow-window check** of Today, unit and module pages at
  375 px and 768 px; fix anything that overflows.
- **Keyboard and screen-reader pass** on the unit page (the briefing, player
  rail, checkpoint form). `aria` labels already exist on progress; check the
  rest.
- **One flaky test.** One full run once failed a test that never failed again
  in 11 runs, probably because port 8000 was in use. Tests that start a
  server should pick a free port.
- **Schema changes.** New columns are added through `ADDED_COLUMNS` in
  `app/db.py`. That is fine for adding columns; the first change that renames
  or removes one needs a real migration step, planned then.

---

## v2.0: Show the work (with M9)

**Goal:** turn what the app already records into a public portfolio. Build
this when the learner reaches M9, not before.

1. **Export a project page** as static HTML: the problem, the Rigor Ladder
   results (split, leakage audit answers, baseline, metric, ablation table
   from the experiment log), and links to the code. One folder, ready for
   GitHub Pages. No server.
2. **A learning record**: modules done, hours, exercises passed, as one page
   that can be linked from a CV.
3. Nothing personal is exported unless chosen: notes stay private by default.

---

## Deliberately not planned

- **Search inside videos.** Asked about before and judged not important.
- **Accounts, cloud sync, a hosted version.** The app is one person on one
  machine; that is why it is simple and free.
- **An AI tutor that answers inside the app by default.** The optional key
  path exists; the default stays "write the question to `inbox/`", which costs
  nothing.
- **Rewriting the frontend in a framework.** No build step is a feature.

---

## Order and size

| Version | Size | Depends on |
|---|---|---|
| v1.1 | small (a day) | nothing; start now |
| v1.2 | large (content-heavy, module by module) | v1.1 feedback, if any |
| v1.3 | medium | v1.2 (needs checkpoints and cards to exist) |
| v1.4 | medium | some real watching done |
| v1.5 | small, pick and choose | — |
| v2.0 | medium | the learner reaching M9 |

After each version: run `python -m pytest -q`, `python -m app.seed --check`,
look at the changed pages in the browser, update `BUILD.md` and this file's
status line, and commit.
