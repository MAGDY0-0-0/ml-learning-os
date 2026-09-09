# How this was built

A working record of the decisions behind *Magdy's ML Journey* — the architecture,
why each piece is shaped the way it is, the bugs that were found on the way, and
the trade-offs that are still open. It is written for the person who has to
change this code next, which is probably you in six months.

If you only want to run it, read the [README](README.md) instead.

---

## Contents

1. [The shape of the problem](#1-the-shape-of-the-problem)
2. [Architecture](#2-architecture)
3. [The data model](#3-the-data-model)
4. [The build-time gate](#4-the-build-time-gate)
5. [The design system](#5-the-design-system)
6. [Motion, without a library](#6-motion-without-a-library)
7. [The player](#7-the-player)
8. [The PDF quick-view](#8-the-pdf-quick-view)
9. [The command palette](#9-the-command-palette)
10. [The mark](#10-the-mark)
11. [Testing](#11-testing)
12. [Bugs found while building](#12-bugs-found-while-building)
13. [What is still open](#13-what-is-still-open)

---

## 1. The shape of the problem

Self-taught ML roadmaps fail in two predictable ways, and both are *interface*
problems as much as content problems.

**You watch a course that doesn't suit you and blame yourself.** The fix is to
make swapping cheap and guilt-free. That is why every unit ships at least three
resources in more than one format, why "swap" is a first-class button rather
than a note in a README, and why the swap form asks *what didn't work* — the
answer is recorded against the resource you rejected, not the one you chose.

**You learn to train models but never learn to tell whether the result is real.**
The fix is a gate. A project cannot be marked complete while a rigor check is
unanswered, and skipping one demands a written justification. The eight leakage
types come from Kapoor & Narayanan's survey, which found these errors in 329
papers across 17 fields — so the checklist is not invented, it is a reproduction
of a real taxonomy.

Everything else in the app is in service of those two ideas.

The other hard constraint: **it runs on one laptop, with no account and no
server bill.** That rules out a lot of comfortable choices and drives most of
the architecture below.

---

## 2. Architecture

A server-rendered multi-page app. FastAPI + Jinja + SQLModel over SQLite.

```
browser ──GET /unit/foo──▶ routes/units.py ──▶ SQLModel/SQLite
                                  │
                                  ├─▶ web.py helpers (progress, notes, ordering)
                                  └─▶ Jinja: base.html + unit.html ──▶ HTML
```

**Why MPA and not React.** Three reasons, in order of weight:

1. The app is a *reading and watching* tool. Almost every interaction is a
   navigation. An SPA would reimplement the browser's job.
2. Cross-document View Transitions are baseline now, so a server-rendered app
   can have the same transition quality an SPA used to be needed for
   (see [§6](#6-motion-without-a-library)).
3. No build step. You clone it, `pip install`, and run. A `node_modules`
   directory would be larger than the entire rest of the project.

The total client-side JavaScript is four hand-written files — `app.js`,
`player.js`, `docview.js`, `review.js` — and no build step, no framework and no
package manager. Two scripts come from a CDN, both fetched lazily and only if
you use the feature: the YouTube IFrame API on first play, and pdf.js on first
PDF open. Fonts and stylesheets are served from this machine, so a cold page
load makes **no external requests at all**.

### Module layout and why it is split this way

```
app/
  main.py        entry point only: lifespan, static mount, router includes
  web.py         templates, template globals, shared view helpers
  db.py          engine, session dependency, the FTS5 virtual table
  models.py      every SQLModel table
  routes/        one module per feature area
```

`web.py` exists because of a circular import. Route modules need
`templates`, `get_progress`, `ordered_resources`; if those lived in `main.py`,
every route would import the app that imports the routes. Pulling the shared
plumbing into its own module breaks the cycle and keeps `main.py` at 40 lines
that do nothing but wire things together.

`routes/` is one file per feature area rather than one giant router, because
the natural unit of change here is a feature ("the library", "the rigor gate"),
not an HTTP verb.

### The request-time helpers

Two template globals in `web.py` are worth calling out because they break the
usual rule that templates should not query.

```python
templates.env.globals["nav_modules"] = nav_modules
templates.env.globals["active_module"] = active_module
```

The left rail is rendered by `base.html` on **every** page, so its data belongs
to no single view. The alternative — every one of ten routes remembering to put
`modules` and `current_module` into its context — is exactly the arrangement
that silently stops working the moment someone adds route eleven. That is not
hypothetical: the first version of the rail *did* read `current_module` and
`due_count` from the route context, no route ever supplied them, and the active
highlight and the review badge were dead for the entire life of that version
without a single error. Deriving them from the request path fixed both.

These helpers open their own short-lived `Session`. On local SQLite that costs
microseconds, and it keeps the chrome decoupled from every view's data.

---

## 3. The data model

Everything lives in `app/models.py`. The tables split into four groups.

**Curriculum** (`Module`, `Unit`, `Resource`, `Assignment`) — the roadmap
itself. Rebuilt from YAML on every seed, so it is effectively derived data.

**Progress** (`Progress`, `ResourceState`, `ResourcePreference`,
`ActiveResource`, `StudySession`) — yours, and the only data that is
irreplaceable.

**Recall and rigor** (`Card`, `Project`, `RubricCheck`, `ExperimentRun`).

**Library** (`LibraryDoc` plus a raw FTS5 table).

Three decisions worth explaining:

**`ActiveResource` is a separate table, not a column on `Unit`.** A unit's
resources come from YAML and are wiped and rebuilt on every reseed. Your choice
of *which* one is primary must survive that. Keeping it in its own table means
`seed.py` can delete and recreate resources freely without touching your state.
`ordered_resources()` in `web.py` applies it at read time by promoting the
chosen row to the front of the list.

**`ResourcePreference` records the resource you rejected, not the one you
picked.** The interesting signal is "StatQuest was too slow for me", not "I am
now watching 3Blue1Brown". `swap_resource()` therefore writes the preference
against `current[0]` — the outgoing primary — before promoting the new one.

**FTS5 is a raw `sqlite3` table, outside SQLModel.** SQLModel has no
virtual-table support. `db.py` creates it with `executescript` and the library
code queries it with raw SQL. Chunks live *only* there; `LibraryDoc` holds
metadata. `ensure_fts()` raises a clear error rather than a mystery failure if
the local SQLite was built without FTS5.

### The migration situation

There is none. `init_db()` calls `SQLModel.metadata.create_all(engine)`, which
creates missing tables but **will not add a column to an existing one.**

This shaped the frontend work directly. The player needs to remember a watch
position, and it turned out `ResourceState.position_seconds` already existed and
was unused — so the player uses it. Auto-logged minutes reuse the existing
`StudySession` table rather than adding a counter column. **The entire frontend
rewrite ships with zero schema changes**, and an existing `data/app.db` keeps
working untouched. That was a deliberate constraint, not luck.

If you do need a column later, add an `ALTER TABLE ... ADD COLUMN` guard in
`init_db()` before reaching for a migration framework.

---

## 4. The build-time gate

The most unusual part of this codebase. `app/seed.py` is not just a loader — it
is a validator that **fails the build** unless the curriculum obeys its rules:

```bash
python -m app.seed --check          # structure + policy
python -m app.seed --check --urls   # ...and every link still resolves
```

It enforces that every unit has at least three resources spanning more than one
format; that each unit's primary is a video, or declares `no_good_video` with a
written reason; that every primary is free; that every resource carries an
honest verdict *and* a caveat; and that every exercise has a starter file and
runnable tests.

The reason to make these hard failures rather than guidelines: the rules
describe the *product promise*. "Swap always gives you a genuinely different
format" is only true if it is impossible to merge a unit that breaks it. A
linter that can be ignored is a comment.

`tests/test_app.py` goes one step further and tests that the validator
**rejects** bad units — a validator nobody has seen fail is not known to work.

This gate paid for itself during the resource expansion. Eight new resources
were inserted by script; the first version of that script walked past
`assignments:` and appended a resource into the exercise list. `--check` caught
it immediately with "starter file missing", the change was reverted, and the
boundary condition fixed. Without the gate that would have shipped.

---

## 5. The design system

All of it is in `app/static/style.css`, driven by custom properties. There is no
Tailwind, no preprocessor, no build.

### Sizing it like a tool

The single highest-impact change in the redesign was **dropping the base font
size from 17px to 15px.** The original was sized like a blog. Interfaces you
operate — as opposed to documents you read — are denser. 16px is reserved for
long-form prose (`--t-md`, used on the guide and recap pages); everything else
sits at 15 and below.

### Type

| Role | Face | Why |
|---|---|---|
| Display | Bricolage Grotesque | Variable, with a width axis — set to `wdth 92` so headings hold together at large sizes |
| UI | Geist | Neutral without being anonymous; excellent at 13–15px |
| Data | Geist Mono | Timecodes, page numbers, module codes, percentages |

Every column of numbers gets `font-variant-numeric: tabular-nums`.

### Colour

A committed dark interface — there is no light variant of the chrome, and
`<meta name="color-scheme" content="dark">` says so.

```
--bg #08090c   --elev-1 #0e1015   --elev-2 #14171e   --elev-3 #1c2029
```

The ground is blue-black rather than neutral grey, and depth comes from four
**layered surfaces** plus translucent hairlines (`rgba(255,255,255,.07)`), not
from a shadow stamped on every block. Translucent lines hold at every elevation;
a fixed hex only looks right on one of them.

Two accents, with strict jobs:

- **Teal `#3fd9c4`** is the system: progress, primary actions, "you are here".
- **Amber `#ffb020`** is *video, and only video.* Because the rule is never
  broken, "watchable" reads at a glance without the word.

Semantic colours (ok / warn / bad) are kept clear of both so a green success
state is never confused with a teal action.

The one exception to the dark world is the **PDF drawer**, which is paper. A
600-page textbook on a near-black ground is punishing, and this is the one
surface you read for an hour. Its tokens (`--paper*`) are separate.

### Geometry

Radius carries meaning rather than being one value everywhere:

```
--r-xs  5px   chips        --r-md  14px  panels
--r-sm  9px   controls     --r-lg  22px  the player — the largest object
```

And **not everything is a card.** Border, fill, radius and shadow each say
"separate object", and spending all four on every block flattens the hierarchy.
Lists are rows separated by rules (`.rows` / `.rowlink`); panels are reserved
for things that genuinely are separate objects. The original design's stack of
identical bordered cards is what made it read as a template.

### Icons

`templates/_icons.html` is an inline SVG sprite, referenced via
`{{ icon('play') }}` (a `Markup` helper in `web.py` that emits a `<use>`).

It replaced emoji. 🧠 📄 🔁 render differently on every platform, at
inconsistent optical sizes, and not at all in some environments. The sprite is
inlined once per page, needs no font and no CDN, works offline, and inherits
`currentColor` — so an icon takes the colour of whatever it sits in for free.

---

## 6. Motion, without a library

The brief was "transitions are from the ice age". The answer, in 2026, is that
**none of this needs a JavaScript animation library.** Total motion runtime
cost: 0 bytes.

### Cross-document View Transitions

```css
@view-transition { navigation: auto; }
::view-transition-group(rail), ::view-transition-group(bar) { animation: none; }
::view-transition-old(page) { animation: pg-out var(--d-1) var(--e-out) both; }
::view-transition-new(page) { animation: pg-in var(--d-snap) var(--e-snap) both; }
```

The rail and the bar carry `view-transition-name` and are explicitly pinned to
`animation: none`, so during a navigation they **hold still** while only the
working surface swaps. That single detail is what makes a server-rendered Jinja
app read as one continuous application rather than a series of documents. It is
the effect people used to adopt an SPA to get.

### Scroll-driven animation

Reveals use `animation-timeline: view()`, and the header earns its shadow with
`animation-timeline: scroll()`:

```css
@supports (animation-timeline: scroll()) {
  .bar { animation: bar-lift linear both;
         animation-timeline: scroll(); animation-range: 0 72px; }
}
```

No scroll listener, no IntersectionObserver, and it runs on the compositor. The
`@supports` guard matters: without it, a browser that ignores the timeline would
render the keyframes as a plain animation, and content could be left stranded at
`opacity: 0`. Behind the guard, the fallback is simply "no animation".

### Real springs

The durations and curves are not guessed. A damped harmonic oscillator was
sampled in Python and emitted as a `linear()` easing function:

```python
w0 = sqrt(stiffness / mass)
zeta = damping / (2 * sqrt(stiffness * mass))
wd = w0 * sqrt(1 - zeta**2)
f = lambda t: 1 - exp(-zeta*w0*t) * (cos(wd*t) + (zeta*w0/wd) * sin(wd*t))
```

Sampled at 49 points, with the settle time (where the system stays within 0.1%
of 1) used as the duration — so the curve and its duration belong together:

| Token | System | Duration |
|---|---|---|
| `--e-snap` / `--d-snap` | m=1, k=300, c=26 | 470ms |
| `--e-spring` / `--d-spring` | m=1, k=180, c=18 | 780ms |

A hand-picked `cubic-bezier` cannot overshoot and settle; `linear()` with
enough samples can, which is what makes the motion feel physical rather than
merely eased.

### Animated disclosure

```css
@supports (interpolate-size: allow-keywords) {
  :root { interpolate-size: allow-keywords; }
  details.alts::details-content {
    block-size: 0; overflow: clip;
    transition: block-size var(--d-2) var(--e-out),
                content-visibility var(--d-2) allow-discrete;
  }
  details.alts[open]::details-content { block-size: auto; }
}
```

Height could not animate to `auto` in CSS until recently, which is the entire
reason accordions have historically needed JavaScript. `interpolate-size` plus
`::details-content` removes that need.

Everything is wrapped in `prefers-reduced-motion`, including turning view
transitions off.

---

## 7. The player

`app/static/player.js`, about 250 lines, no dependencies.

Before: `<iframe src="youtube.com/embed/...">`. You watched, then typed "25"
into a box to log the time you had just spent.

### What it does

- **Poster first.** Nothing is requested from YouTube until you press play, so a
  unit page still loads instantly, and offline, when you are only there for the
  notes. The IFrame API script itself is injected on that first click.
- **Resumes where you stopped** — position POSTed every 5 seconds and on
  `pagehide`.
- **Auto-logs the minutes you actually watched.** The box is gone.
- **Auto-marks watched** at 90%, or on `ENDED`.
- **Keyboard**: `k` play/pause, `j`/`l` ±10s, `,`/`.` playlist parts.
- **"Open on YouTube where you are"** rebuilds the watch URL with your live
  timestamp.
- **Playlist rail** built from `getPlaylist()` — the list YouTube actually
  returns, so it cannot drift out of sync with a hand-maintained one in YAML.

### The state protocol

Three JSON endpoints in `routes/units.py`:

```
POST /resource/{id}/position   {seconds}
POST /resource/{id}/watched    {done}
POST /unit/{slug}/log-auto     {minutes}
```

They return a small JSON body and **never a redirect**. These are called through
`navigator.sendBeacon` during page unload; a 303 would be followed and would
waste a full page render on a page that is already leaving.

`log-auto` caps a single call at 30 minutes. A beacon that fires twice, or a tab
left open, must never be able to claim an hour of study you did not do. The cap
is tested.

### Degradation

Every step degrades. No network: the poster stays, the links still work, the
forms underneath are untouched. JavaScript off: the page is a normal document
with working `<form>` posts. The player is an enhancement over a page that
already functions.

---

## 8. The PDF quick-view

`app/static/docview.js` + `GET /library/doc/{id}`.

Search already knew the page a phrase was on — it printed "page 217" and left
you to go and find it. Now the hit is a control: clicking it opens the PDF at
that page in a drawer over the page you were on, so you never lose the unit, or
the video's position, to look something up.

pdf.js is fetched from cdnjs on first open only. It pins **3.11.174**, the UMD
build, deliberately: the 4.x files on the CDN are ES modules that export rather
than defining `window.pdfjsLib`, which a plain `<script>` tag cannot reach. That
was found by loading 4.x first and watching it resolve to `undefined`.

### The path guard

```python
doc = s.get(library.LibraryDoc, doc_id)
if doc is None: raise HTTPException(404)
path = Path(doc.path).resolve()
root = library.LIBRARY_DIR.resolve()
if not path.is_relative_to(root) or not path.is_file():
    raise HTTPException(404)
```

Two independent conditions: the id has to resolve to an indexed row, **and** the
resolved path has to sit under `library/`. Checking only the first would turn a
doctored database row into an arbitrary file read. There is a test that inserts
a row pointing at `app/main.py` and asserts a 404.

The drawer is a native `<dialog>` with `showModal()` — focus trapping, `Esc`,
and the backdrop come from the platform. "Cite into notes" appends your
selection plus *Title, p.N* to `notes/{unit}.md`, which is the same file Claude
reads when you ask for help.

---

## 9. The command palette

`Ctrl/Cmd-K`, or `/`. `app/static/app.js`.

The index — every unit, module and project — is fetched once from
`/api/search-index` on first open and held for the visit. The curriculum does
not change while you study, so re-fetching would be pure waste.

Also in that file: toasts, and `data-quiet` forms. A form marked `data-quiet`
posts in the background and confirms with a toast instead of round-tripping the
whole page, so saving a note no longer scrolls you back to the top. It is
progressive: remove the JS and it is an ordinary form post.

---

## 10. The mark

`templates/_logo.html` is a Jinja macro, not an image file, because the ring is
**live**:

```jinja
{{ logo(overall, 30, "Magdy's ML Journey") }}
```

Built to spec: a 64×64 tile at corner radius 16, a ring of r=21 and stroke 6
starting at 12 o'clock (circumference 2π·21 = 131.95), and an M 16 wide × 14
tall at stroke 3.5, centred. Below 20px the M is dropped and the ring stands
alone.

Its colours are the app's own tokens, so it can never drift from the interface:

```css
--logo-tile:  #0b0e13;
--logo-track: color-mix(in srgb, var(--accent) 22%, #0b0e13);
--logo-ring:  var(--accent);
```

The track is the accent knocked back into the tile rather than a neutral grey,
so the *unfinished* arc still belongs to the palette. Change `--accent` and the
logo follows; there is no second brand palette to keep in sync.

The favicon is the same geometry with the ring closed — a tab icon should state
the identity, not today's progress, and a partial arc is illegible at 16px.

---

## 11. Testing

76 tests, `python -m pytest tests/ -q`. They target the things that fail
*silently*, not line coverage.

`tests/test_app.py`
- SM-2 against known vectors, plus its failure and ease-floor behaviour
- the curriculum rules — **including that the validator rejects bad units**
- the rigor gate blocks and releases correctly
- the two sandbox properties that matter: an infinite loop **times out**
  instead of hanging the server, and submitted code **cannot reach the network**

`tests/test_frontend.py`
- YouTube id splitting across all four URL shapes
- the player endpoints, including the 30-minute cap
- the PDF route's path guard (a row pointing outside `library/` → 404)
- the rail deriving its own active state
- the logo macro at 0 / 33 / 100%, out-of-range clamping, and the 20px cutoff
- the oEmbed link checker: a dead video must fail, a live one must pass
- platform detection, and that a non-embeddable primary never renders an
  empty player
- the R5 ablation gate refusing to pass under two labels
- review's JSON grading, and that the plain form still works without it
- swap preferences counted, and rejected alternates sinking
- **that no template pulls a stylesheet or font from the internet**

### The one thing to know before adding a test

**The app has exactly one database and it is the learner's real one.** The first
version of `test_frontend.py` left 30 minutes of study time and a watch position
behind on every run. There is now an autouse `restore_progress` fixture that
snapshots the rows those tests touch — `Progress`, `ResourceState`, and any
`StudySession` created during the test — and puts them back.

If you add a test that writes, extend that fixture. Verified by running the
suite three times and confirming the tables come back unchanged.

---

## 12. Bugs found while building

Kept because each one is a class of mistake, not a one-off.

**`text-overflow` does nothing on an inline element.** Module titles in the rail
and subtitles in list rows were `<span>`s. Instead of eliding they overflowed
their track, and in the rail that forced a horizontal scrollbar. Fixed with
`display: block` (and `-webkit-line-clamp: 2` for the rail, because ten titles
all truncating to one line read as damage — these are sentences, not labels).

**Grid children default to `min-width: auto`, not 0.** A nowrap subtitle
inflated its own track and pushed entire rows past the page. Fixed with
`.rowlink > * { min-width: 0 }`.

**Template context that no route supplies fails silently.** `current_module` and
`due_count` were read by `base.html` and provided by nobody. No error, no
warning — the features simply never appeared. Now derived from the request path
in `web.py`. Jinja's default `Undefined` is falsy, which is convenient and
dangerous in equal measure.

**A line-based YAML inserter must know where a list ends.** The script that
added eight resources walked past `assignments:` and appended into the exercise
list. The boundary needs to stop at a *sibling key* at the same indent, not only
at an outdent. Caught by `seed --check`, not by review.

**Two indentation styles in one directory.** `m4_classical.yaml` nests resources
at indent 6; every other module file uses 2. The inserter now reads the indent
from the file rather than assuming one.

**pdf.js 4.x on cdnjs is ESM.** It does not define `window.pdfjsLib`. Pinned to
the 3.11.174 UMD build.

**A deleted YouTube video answers HTTP 200 on its watch page.** So the obvious
link check passed every dead video in the curriculum — 59 of them at the time,
the format the app is built around. oEmbed answers honestly (400 for a video,
404 for a playlist) and is what the checker uses now.

**YouTube error 150 does not mean what it says.** Nominally "embedding
disabled", it is also returned for a video that does not exist. The player's
first draft therefore told me a nonexistent video "plays normally on YouTube".
Error copy must not assert what the error code cannot prove.

**A test suite that meets a fresh database.** All 24 frontend tests errored on
CI's empty checkout because they assumed a seeded curriculum. Found by moving
the real database aside and running them, rather than by watching CI fail.

**A hardcoded slug turned a test into a skip.** `test_alternates_you_rejected`
named a unit that later stopped having two same-format alternates, so it
quietly stopped running. It now searches for a qualifying unit. A skipped test
reads as green.

---

## 13. What is still open

Honest list of what was left undone, and why.

- **`tour.html` and `recap.html` were restyled, not rebuilt.** They are
  long-form reading pages — one includes an Arabic RTL section — so they get a
  document treatment (`body[data-doc]`: prose measure, display headings) rather
  than a markup rewrite. Restructuring 16KB of prose was more risk than value.
- **No schema migrations.** Still true, and still fine: platform and
  embeddability turned out to be functions of the URL host rather than columns,
  so nothing has needed one yet. The first feature that does will need an
  `ALTER TABLE` guard in `init_db()`.
- **Chapters are playlist-derived only.** The YouTube API exposes playlist
  entries but not a single video's chapters. A `chapters:` key in the
  curriculum YAML would work, but hand-authoring them for 133 resources is not
  something anyone would keep accurate, so it was left out rather than shipped
  half-populated.
- **Tests share the learner's database.** Every mutating test now snapshots
  and restores what it touches — progress, watch positions, study sessions,
  card schedules, experiment runs, swap preferences — and a full run leaves
  zero residue. The real fix is still to point the engine at a temp file.
- ~~Fonts come from Google Fonts.~~ **Done.** All three families are vendored
  into `app/static/fonts/` (263 KB, latin and latin-ext only) and served by
  `fonts.css`. A cold load now makes **zero external requests**, verified in
  the browser. pdf.js is still fetched from cdnjs on the first PDF open — that
  one is still outstanding.
- ~~`--urls` is slow.~~ **Done.** Parallelised, and 138 links now take about
  8 seconds instead of minutes.

---

## Working on it

```bash
.venv\Scripts\activate
python -m app.seed --check          # before committing curriculum changes
python -m pytest tests/ -q          # before committing anything
python -m uvicorn app.main:app --port 8000 --reload
```

Two rules that keep the codebase honest:

1. **If you change `curriculum/`, run `--check`.** The rules are the product
   promise, and the gate is the only thing enforcing them.
2. **If you add a colour, add a token.** Every value in the interface comes from
   `:root`. A literal hex in a component is how a design system dies.
