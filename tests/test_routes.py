"""Route-level and regression tests. Uses the isolated, seeded DB from conftest."""

from __future__ import annotations

import copy

from sqlmodel import Session, select

from app import library, runner, seed, tutor
from app.db import engine, raw_connection
from app.experiments import ablation_table
from app.models import (
    ActiveResource, Card, CheckStatus, ExperimentRun, Progress, Project, Resource,
    ResourcePreference, RubricCheck, Submission, Unit,
)
from app.routes import units as units_routes
from app.web import ordered_resources


def _unit(s: Session, slug: str) -> Unit:
    return s.exec(select(Unit).where(Unit.slug == slug)).one()


# --------------------------------------------------------------------------
# library search must not render PDF text as HTML
# --------------------------------------------------------------------------


def test_library_snippet_escapes_pdf_text_but_keeps_highlight(client):
    conn = raw_connection()
    try:
        conn.execute(
            "INSERT INTO library_chunk (doc_path, title, page, text) VALUES (?,?,?,?)",
            ("library/evil.pdf", "Evil", 3, "<script>alert(1)</script> zebrafishleakage here"),
        )
        conn.commit()

        hits = library.search("zebrafishleakage")
        assert hits and hits[0].page == 3
        assert "<script>" not in hits[0].snippet
        assert "&lt;script&gt;" in hits[0].snippet
        assert "<mark>zebrafishleakage</mark>" in hits[0].snippet

        page = client.get("/library", params={"q": "zebrafishleakage"}).text
        assert "<script>alert(1)</script>" not in page
        assert "<mark>zebrafishleakage</mark>" in page
    finally:
        conn.execute("DELETE FROM library_chunk WHERE doc_path = 'library/evil.pdf'")
        conn.commit()
        conn.close()


def test_library_search_survives_fts_syntax_errors():
    assert library.search('unbalanced "quote') == []


# --------------------------------------------------------------------------
# sandbox runner
# --------------------------------------------------------------------------


def test_parse_counts_reads_only_the_final_summary():
    out = "\n".join([
        "99 passed",                       # printed by the submission
        "AssertionError: 7 failed",
        "1 failed, 2 passed, 1 error in 0.12s",
    ])
    assert runner._parse_counts(out) == (2, 4)
    # a printed count must not survive into a summary that lacks that kind
    assert runner._parse_counts("50 passed\n1 failed in 0.01s") == (0, 1)


def test_parse_counts_handles_banner_form_and_no_summary():
    assert runner._parse_counts("===== 3 passed, 1 warning in 1.02s =====") == (3, 3)
    assert runner._parse_counts("no tests ran in 0.01s") == (0, 0)
    assert runner._parse_counts("") == (0, 0)


def test_submission_cannot_fake_its_score_by_printing(tmp_path):
    sub = tmp_path / "sol.py"
    sub.write_text("def f():\n    print('50 passed')\n    return 1\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_f.py").write_text(
        "import solution\ndef test_f():\n    assert solution.f() == 2\n", encoding="utf-8"
    )
    result = runner.run_submission(sub, tests, timeout=30)
    assert (result.passed, result.total) == (0, 1), result.output


def test_submission_cannot_read_api_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("MY_SERVICE_TOKEN", "tok-should-not-leak")
    sub = tmp_path / "sol.py"
    sub.write_text("import os\nENV = dict(os.environ)\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_env.py").write_text(
        "import solution\n"
        "def test_no_secrets():\n"
        "    assert 'GEMINI_API_KEY' not in solution.ENV\n"
        "    assert 'MY_SERVICE_TOKEN' not in solution.ENV\n",
        encoding="utf-8",
    )
    result = runner.run_submission(sub, tests, timeout=30)
    assert result.ok, result.output


# --------------------------------------------------------------------------
# review
# --------------------------------------------------------------------------


def test_grading_out_of_range_quality_is_ignored_not_500(client):
    with Session(engine) as s:
        card = s.exec(select(Card)).first()
        before = (card.ease, card.interval_days, card.repetitions)
        card_id = card.id
    resp = client.post(f"/review/{card_id}", data={"quality": "9"})
    assert resp.status_code == 303
    with Session(engine) as s:
        card = s.get(Card, card_id)
        assert (card.ease, card.interval_days, card.repetitions) == before


def test_grading_a_card_schedules_it(client):
    with Session(engine) as s:
        card = s.exec(select(Card).where(Card.repetitions == 0)).first()
        card_id = card.id
    assert client.post(f"/review/{card_id}", data={"quality": "4"}).status_code == 303
    with Session(engine) as s:
        card = s.get(Card, card_id)
        assert card.repetitions == 1 and card.interval_days == 1


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------


def test_log_time_rejects_non_positive_minutes(client):
    with Session(engine) as s:
        uid = _unit(s, "m2-pandas").id
    client.post("/unit/m2-pandas/log", data={"minutes": "-500"})
    client.post("/unit/m2-pandas/log", data={"minutes": "0"})
    client.post("/unit/m2-pandas/log", data={"minutes": "25"})
    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == uid)).one()
        assert p.minutes_logged == 25
        assert p.status == "in_progress"


def test_notes_only_saved_for_real_units(client):
    client.post("/unit/not-a-real-unit/notes", data={"notes": "x"})
    assert not (units_routes.notes_path("not-a-real-unit")).exists()

    client.post("/unit/m2-pandas/notes", data={"notes": "groupby is split-apply-combine"})
    assert "split-apply-combine" in client.get("/unit/m2-pandas").text


def test_swap_promotes_choice_and_blames_the_outgoing_primary(client):
    with Session(engine) as s:
        u = _unit(s, "m2-pandas")
        before = ordered_resources(s, u)
        outgoing, chosen = before[0], before[1]
    resp = client.post(
        "/unit/m2-pandas/swap", data={"resource_id": chosen.id, "reason": "too_slow"}
    )
    assert resp.status_code == 303
    with Session(engine) as s:
        u = _unit(s, "m2-pandas")
        assert ordered_resources(s, u)[0].id == chosen.id
        pref = s.exec(
            select(ResourcePreference).where(ResourcePreference.resource_id == outgoing.id)
        ).all()
        assert pref and pref[-1].reason == "too_slow"


def test_asking_without_a_key_writes_the_inbox(client):
    assert tutor.provider_status().name == "inbox"
    resp = client.post("/unit/m2-pandas/ask", data={"question": "Why merge vs join?"})
    assert resp.status_code == 303
    files = list(tutor.INBOX.glob("ask-*.md"))
    assert len(files) == 1
    assert "Why merge vs join?" in files[0].read_text(encoding="utf-8")


def test_two_inbox_writes_in_the_same_second_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setattr(tutor, "INBOX", tmp_path)
    a = tutor.write_inbox("ask", "same", "one")
    b = tutor.write_inbox("ask", "same", "two")
    assert a != b and a.read_text() == "one" and b.read_text() == "two"


# --------------------------------------------------------------------------
# projects: the rigor gate over HTTP
# --------------------------------------------------------------------------


def test_project_cannot_complete_while_checks_unanswered(client):
    resp = client.post("/project/p5-portfolio/complete")
    assert resp.headers["location"].endswith("?err=blocked")
    with Session(engine) as s:
        assert s.exec(select(Project).where(Project.slug == "p5-portfolio")).one().completed is False


def test_skip_requires_a_justification_and_is_sent_to_the_inbox(client):
    client.get("/project/p5-portfolio")  # creates the checks
    resp = client.post("/project/p5-portfolio/check/L3.1", data={"status": "skipped"})
    assert resp.headers["location"].endswith("?err=justify")

    client.post(
        "/project/p5-portfolio/check/L3.1",
        data={"status": "skipped", "justification": "no time column in this data"},
    )
    with Session(engine) as s:
        p = s.exec(select(Project).where(Project.slug == "p5-portfolio")).one()
        c = s.exec(
            select(RubricCheck).where(RubricCheck.project_id == p.id, RubricCheck.code == "L3.1")
        ).one()
        assert c.status == CheckStatus.skipped
    assert list(tutor.INBOX.glob("rubric-skip-*.md"))


def test_project_completes_once_every_check_is_resolved(client):
    client.get("/project/p5-portfolio")
    with Session(engine) as s:
        p = s.exec(select(Project).where(Project.slug == "p5-portfolio")).one()
        codes = [c.code for c in s.exec(select(RubricCheck).where(RubricCheck.project_id == p.id))]
    for code in codes:
        if code == "R5":
            # R5 only passes on evidence (two logged variants), which this test
            # has none of, so it is resolved the other honest way: a written skip.
            client.post(f"/project/p5-portfolio/check/{code}",
                        data={"status": "skipped", "justification": "no ablation in this test"})
        else:
            client.post(f"/project/p5-portfolio/check/{code}", data={"status": "passed"})
    resp = client.post("/project/p5-portfolio/complete")
    assert "err" not in resp.headers["location"]
    with Session(engine) as s:
        p = s.exec(select(Project).where(Project.slug == "p5-portfolio")).one()
        assert p.completed is True
        # leave the shared DB as we found it
        p.completed, p.completed_at = False, None
        for c in s.exec(select(RubricCheck).where(RubricCheck.project_id == p.id)):
            c.status, c.justification = CheckStatus.unchecked, ""
        s.commit()


# --------------------------------------------------------------------------
# submissions
# --------------------------------------------------------------------------


def test_submitting_the_starter_runs_the_exercise_tests(client):
    page = client.get("/assignment/m0-idioms-drill")
    assert page.status_code == 200
    with Session(engine) as s:
        from app.models import Assignment

        a = s.exec(select(Assignment).where(Assignment.slug == "m0-idioms-drill")).one()
        starter = runner.resolve(a.starter_path).read_text(encoding="utf-8")
        aid = a.id

    resp = client.post("/assignment/m0-idioms-drill/submit", data={"code": starter})
    assert resp.status_code == 303
    with Session(engine) as s:
        sub = s.exec(
            select(Submission).where(Submission.assignment_id == aid).order_by(Submission.id.desc())
        ).first()
        assert sub.tests_total > 0, sub.stdout
        assert not sub.timed_out
        sid = sub.id

    resp = client.post(f"/submission/{sid}/review")
    assert resp.status_code == 303
    assert list(tutor.INBOX.glob("review-*.md"))


# --------------------------------------------------------------------------
# seeding
# --------------------------------------------------------------------------


def test_reseed_drops_rows_that_point_at_a_removed_resource():
    modules = seed.load_modules()
    with Session(engine) as s:
        u = _unit(s, "m2-pandas")
        last = s.exec(
            select(Resource).where(Resource.unit_id == u.id).order_by(Resource.rank.desc())
        ).first()
        active = s.exec(select(ActiveResource).where(ActiveResource.unit_id == u.id)).first()
        if active is None:
            s.add(ActiveResource(unit_id=u.id, resource_id=last.id))
        else:
            active.resource_id = last.id
        s.add(ResourcePreference(resource_id=last.id))
        s.commit()
        removed_id, removed_url = last.id, last.url

    trimmed = copy.deepcopy(modules)
    for m in trimmed:
        for unit in m.get("units") or []:
            if unit["slug"] == "m2-pandas":
                unit["resources"] = [r for r in unit["resources"] if r["url"] != removed_url]
    try:
        seed.seed(trimmed)
        with Session(engine) as s:
            assert s.get(Resource, removed_id) is None
            assert not s.exec(
                select(ActiveResource).where(ActiveResource.resource_id == removed_id)
            ).all()
            assert not s.exec(
                select(ResourcePreference).where(ResourcePreference.resource_id == removed_id)
            ).all()
    finally:
        seed.seed(modules)


def test_seed_is_idempotent():
    with Session(engine) as s:
        before = (
            len(s.exec(select(Unit)).all()),
            len(s.exec(select(Resource)).all()),
            len(s.exec(select(Card)).all()),
        )
    seed.seed(seed.load_modules())
    with Session(engine) as s:
        after = (
            len(s.exec(select(Unit)).all()),
            len(s.exec(select(Resource)).all()),
            len(s.exec(select(Card)).all()),
        )
    assert before == after


# --------------------------------------------------------------------------
# experiments
# --------------------------------------------------------------------------


def test_ablation_table_reports_mean_and_spread_per_label():
    runs = [
        ExperimentRun(label="full", seed=0, metrics_json='{"acc": 0.80}'),
        ExperimentRun(label="full", seed=1, metrics_json='{"acc": 0.84}'),
        ExperimentRun(label="no-aug", seed=0, metrics_json='{"acc": 0.70}'),
        ExperimentRun(label="other-metric", seed=0, metrics_json='{"f1": 0.5}'),
    ]
    rows = ablation_table(runs, "acc")
    assert [r.label for r in rows] == ["full", "no-aug"]
    assert abs(rows[0].mean - 0.82) < 1e-9 and rows[0].spread > 0
    assert rows[0].seeds == [0, 1]
    assert rows[1].n == 1 and rows[1].spread == 0.0
