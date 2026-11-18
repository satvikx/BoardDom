from unittest.mock import patch
from uuid import UUID

from conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    ORIGIN,
    PHOTOSYNTHESIS,
    approved,
    extracted_source,
    register,
    wait,
    workspace,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_accounts import login, make_student

from app.ai import AIError
from app.models.entities import (
    ArtifactVersion,
    SourceChunk,
    SourceDocument,
)
from app.services import citations
from app.services.course_content import parse_passages
from app.services.demo_ai import demo_unit_notes
from app.services.retrieval import ensure_index, split_text

# ---- pure helpers ---------------------------------------------------------------------------


def test_split_text_respects_limit_and_paragraphs():
    text = "One.\n\nTwo two.\n\n" + "word " * 400
    chunks = split_text(text, limit=100)
    assert chunks[0] == "One.\n\nTwo two."
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).count("word") == 400


def test_split_text_starts_a_chunk_at_each_heading():
    text = "# A\n\nAlpha text.\n\n# B\n\nBeta text.\n\nMore beta."
    assert split_text(text) == ["# A\n\nAlpha text.", "# B\n\nBeta text.\n\nMore beta."]


def test_citation_check_rules():
    md = "# U\n\n## A\n\nFact [C1] and [C2].\n\n## B\n\nNo source.\n\n## Summary\n\nok"
    result = citations.check(md, {"C1", "C2"})
    assert result.ok and result.used == ["C1", "C2"] and result.invalid == []
    assert result.warnings == ["Section “B” has no citation."]
    bad = citations.check("## A\n\nx [C1] [C9] [W1]", {"C1"})
    assert not bad.ok and bad.invalid == ["C9", "W1"]
    assert not citations.check("## A\n\nnothing", {"C1"}).ok


def test_demo_notes_cite_only_given_passages():
    prompt = "Topics: a; b\n\nSOURCE PASSAGES\n[C4] (x.md, p. 1)\nFirst. Second. Third.\n"
    prompt += "[C9] (x.md)\nOther text here.\nEND PASSAGES"
    assert [p[0] for p in parse_passages(prompt)] == [4, 9]
    draft = demo_unit_notes("", prompt)
    found = set(citations.markers(str(draft)))
    assert found and found <= {"C4", "C9"}


def test_fake_embeddings_are_topical(signed_in, app):
    from app.ai.fake_provider import FakeProvider
    from app.services.retrieval import cosine, search

    fake = FakeProvider()
    leaf, cell, quiz = fake.embed(
        ["Chlorophyll in leaves absorbs light", "Mitochondria release energy", "capital France"],
        purpose="t",
    )
    [query] = fake.embed(["How do leaves absorb light?"], purpose="t")
    assert cosine(query, leaf) > 0.5 > cosine(query, cell)
    assert cosine(query, quiz) == 0
    base = workspace(signed_in)
    extracted_source(app, base, signed_in, ["\n\n".join(PHOTOSYNTHESIS)])
    with app.state.session_factory() as db:
        workspace_id = UUID(base.rsplit("/", 1)[1])
        ensure_index(db, app.state.ai, workspace_id)
        for query, expected in [
            ("what do mitochondria do with glucose", "# Respiration"),
            ("chlorophyll light leaves", "# Photosynthesis"),
            ("producers consumers fox", "# Food chains"),
        ]:
            assert search(db, app.state.ai, workspace_id, query, k=1)[0].text.startswith(expected)


# ---- indexing -------------------------------------------------------------------------------


def test_index_is_incremental_and_never_reuses_labels(signed_in, app):
    base = workspace(signed_in)
    workspace_id = UUID(base.rsplit("/", 1)[1])
    first = extracted_source(app, base, signed_in)
    with app.state.session_factory() as db:
        assert ensure_index(db, app.state.ai, workspace_id) == 3
        labels = sorted(db.scalars(select(SourceChunk.ordinal)))
        assert labels == [1, 2, 3]
        assert ensure_index(db, app.state.ai, workspace_id) == 3  # unchanged: no re-embed
        assert sorted(db.scalars(select(SourceChunk.ordinal))) == [1, 2, 3]
        db.get(SourceDocument, UUID(first)).content_revision = 2  # teacher corrected text
        db.commit()
        ensure_index(db, app.state.ai, workspace_id)
        assert sorted(db.scalars(select(SourceChunk.ordinal))) == [4, 5, 6]
    assert signed_in.delete(f"{base}/documents/{first}").status_code == 204
    extracted_source(app, base, signed_in, ["# New\n\nFresh material."], "new.md")
    with app.state.session_factory() as db:
        ensure_index(db, app.state.ai, workspace_id)
        assert list(db.scalars(select(SourceChunk.ordinal))) == [7]


# ---- syllabus -------------------------------------------------------------------------------


def test_syllabus_generate_edit_approve_reopen(course, signed_in, app):
    assert signed_in.get(course + "/syllabus").json() is None
    job = wait(app, signed_in.post(course + "/syllabus/generate"))
    assert "Drafted 3 units" in job.message
    syllabus = signed_in.get(course + "/syllabus").json()
    assert syllabus["status"] == "draft" and len(syllabus["units"]) == 3
    assert syllabus["units"][0]["title"].startswith("Unit 1:")
    assert syllabus["units"][0]["topics"]

    keep = syllabus["units"][:2]
    edited = signed_in.put(
        course + "/syllabus",
        json={
            "expected_revision": syllabus["revision"],
            "units": [
                {"id": keep[1]["id"], "title": "Respiration first", "topics": ["ATP"]},
                {"id": keep[0]["id"], "title": keep[0]["title"], "summary": "s"},
                {"title": "  New unit  ", "topics": ["  extra  "]},
            ],
        },
    )
    assert edited.status_code == 200, edited.text
    units = edited.json()["units"]
    assert [u["title"] for u in units] == ["Respiration first", keep[0]["title"], "New unit"]
    assert units[0]["id"] == keep[1]["id"] and units[2]["topics"] == ["extra"]
    stale = {"expected_revision": syllabus["revision"], "units": []}
    assert signed_in.put(course + "/syllabus", json=stale).status_code == 409

    revision = edited.json()["revision"]
    approve = signed_in.post(course + "/syllabus/approve", json={"expected_revision": revision})
    assert approve.status_code == 200 and approve.json()["status"] == "approved"
    revision = approve.json()["revision"]
    locked = {"expected_revision": revision, "units": [{"title": "x"}]}
    assert signed_in.put(course + "/syllabus", json=locked).status_code == 409
    assert signed_in.post(course + "/syllabus/generate").status_code == 409
    reopened = signed_in.post(course + "/syllabus/reopen", json={"expected_revision": revision})
    assert reopened.json()["status"] == "draft"


def test_manual_syllabus_and_empty_approve(signed_in):
    base = workspace(signed_in)
    created = signed_in.put(
        base + "/syllabus",
        json={"expected_revision": 0, "units": [{"title": "Hand-made unit"}]},
    )
    assert created.status_code == 200 and created.json()["revision"] == 1
    emptied = signed_in.put(base + "/syllabus", json={"expected_revision": 1, "units": []})
    blocked = signed_in.post(
        base + "/syllabus/approve", json={"expected_revision": emptied.json()["revision"]}
    )
    assert blocked.status_code == 422


def test_syllabus_without_sources_fails_clearly(signed_in, app):
    base = workspace(signed_in)
    job = wait(app, signed_in.post(base + "/syllabus/generate"), expect="failed")
    assert "No extracted sources" in job.message
    jobs = signed_in.get(base + "/jobs").json()
    assert jobs[0]["status"] == "failed" and jobs[0]["message"] == job.message


# ---- notes ----------------------------------------------------------------------------------


def test_notes_generate_cite_edit_history_restore(course, signed_in, app):
    assert signed_in.post(course + "/notes/generate", json={}).status_code == 409
    syllabus = approved(signed_in, app, course)
    job = wait(app, signed_in.post(course + "/notes/generate", json={}))
    assert job.message == "Generated notes for 3 of 3 unit(s)." and job.progress == 3

    listing = signed_in.get(course + "/notes").json()
    assert [n["unit_id"] for n in listing] == [u["id"] for u in syllabus["units"]]
    assert all(n["current_version"] == 1 for n in listing)
    notes_url = f"{course}/notes/{listing[0]['artifact_id']}"
    notes = signed_in.get(notes_url).json()
    assert notes["markdown"].startswith("# Unit 1:")
    assert "**Worked example.**" in notes["markdown"] and "## Key terms" in notes["markdown"]
    used = set(citations.markers(notes["markdown"]))
    assert used and used == set(notes["citations"])
    with app.state.session_factory() as db:
        real = {f"C{o}" for o in db.scalars(select(SourceChunk.ordinal))}
    assert used <= real
    citation = next(iter(notes["citations"].values()))
    assert citation["document"] == "notes.md" and citation["page"] and citation["excerpt"]

    for bad in ("[C999]", "[W1]"):
        rejected = signed_in.put(
            notes_url, json={"markdown": f"## X\n\nClaim {bad}", "expected_version": 1}
        )
        assert rejected.status_code == 422 and bad in rejected.json()["detail"]
    good = "## Edited\n\nTeacher wording [C1]."
    saved = signed_in.put(notes_url, json={"markdown": good, "expected_version": 1})
    assert saved.status_code == 200, saved.text
    assert saved.json()["number"] == 2 and saved.json()["origin"] == "edited"
    assert list(saved.json()["citations"]) == ["C1"]
    stale = signed_in.put(notes_url, json={"markdown": good, "expected_version": 1})
    assert stale.status_code == 409

    old = signed_in.get(notes_url, params={"number": 1}).json()
    assert old["number"] == 1 and old["current_version"] == 2
    restored = signed_in.post(notes_url + "/restore/1", json={"expected_version": 2})
    assert restored.json()["number"] == 3 and restored.json()["markdown"] == notes["markdown"]
    assert [v["origin"] for v in restored.json()["versions"]] == [
        "restored",
        "edited",
        "generated",
    ]
    assert restored.json()["versions"][0]["created_by_name"] == "Alex Teacher"

    # Regenerate one unit: history grows, nothing is lost.
    unit_ids = [listing[0]["unit_id"]]
    wait(app, signed_in.post(course + "/notes/generate", json={"unit_ids": unit_ids}))
    assert signed_in.get(notes_url).json()["current_version"] == 4


def test_invalid_citations_retry_then_fail(course, signed_in, app):
    approved(signed_in, app, course)
    calls = []

    def always_bad(instructions, prompt):
        calls.append(prompt)
        return {
            "sections": [{"heading": "H", "explanation": "Made up [C999]", "worked_example": None}],
            "key_terms": [],
            "summary": "s",
        }

    app.state.ai.structured_builders["UnitNotesDraft"] = always_bad
    job = wait(app, signed_in.post(course + "/notes/generate", json={}), expect="failed")
    assert "citation check failed" in job.message and "C999" in job.message
    assert len(calls) == 6  # 3 units x (first try + one corrective retry)
    assert "previous answer was rejected" in calls[1]
    with app.state.session_factory() as db:
        assert db.scalars(select(ArtifactVersion)).all() == []


def test_corrective_retry_can_succeed(course, signed_in, app):
    approved(signed_in, app, course)
    from app.services.demo_ai import demo_unit_notes as good

    attempts = []

    def bad_then_good(instructions, prompt):
        attempts.append(1)
        if len(attempts) == 1:
            return {"sections": [], "key_terms": [], "summary": "no citations"}
        return good(instructions, prompt)

    app.state.ai.structured_builders["UnitNotesDraft"] = bad_then_good
    job = wait(app, signed_in.post(course + "/notes/generate", json={}))
    assert job.message == "Generated notes for 3 of 3 unit(s)." and len(attempts) == 4


def test_ai_failure_stops_job_with_friendly_message(course, signed_in, app):
    approved(signed_in, app, course)

    def busy(instructions, prompt):
        raise AIError("ai_busy", "The AI service is busy. Please retry shortly.", 503)

    app.state.ai.structured_builders["UnitNotesDraft"] = busy
    job = wait(app, signed_in.post(course + "/notes/generate", json={}), expect="failed")
    assert job.message == "The AI service is busy. Please retry shortly."


def test_removing_a_unit_removes_its_notes(course, signed_in, app):
    approved(signed_in, app, course)
    wait(app, signed_in.post(course + "/notes/generate", json={}))
    syllabus = signed_in.get(course + "/syllabus").json()
    reopened = signed_in.post(
        course + "/syllabus/reopen", json={"expected_revision": syllabus["revision"]}
    ).json()
    first = reopened["units"][0]
    signed_in.put(
        course + "/syllabus",
        json={
            "expected_revision": reopened["revision"],
            "units": [{"id": first["id"], "title": "Only"}],
        },
    )
    notes = signed_in.get(course + "/notes").json()
    assert len(notes) == 1 and notes[0]["current_version"] == 1
    with app.state.session_factory() as db:
        assert len(db.scalars(select(ArtifactVersion)).all()) == 1


# ---- jobs and access ------------------------------------------------------------------------


def test_one_active_job_per_kind_and_restart_recovery(course, signed_in, app):
    with patch.object(app.state.jobs.pool, "submit"):
        first = signed_in.post(course + "/syllabus/generate")
        assert first.status_code == 202 and first.json()["status"] == "queued"
        assert signed_in.post(course + "/syllabus/generate").status_code == 409
    app.state.jobs.recover()
    job = signed_in.get(f"{course}/jobs/{first.json()['id']}").json()
    assert job["status"] == "failed" and "restarted" in job["message"]
    wait(app, signed_in.post(course + "/syllabus/generate"))


def test_other_users_cannot_reach_course_content(course, signed_in, app):
    approved(signed_in, app, course)
    wait(app, signed_in.post(course + "/notes/generate", json={}))
    notes_url = f"{course}/notes/{signed_in.get(course + '/notes').json()[0]['artifact_id']}"
    syllabus_body = {"expected_revision": 0, "units": []}
    notes_body = {"markdown": "x", "expected_version": 1}
    paths = [
        ("GET", course + "/syllabus", None),
        ("POST", course + "/syllabus/generate", None),
        ("PUT", course + "/syllabus", syllabus_body),
        ("GET", course + "/notes", None),
        ("POST", course + "/notes/generate", {}),
        ("GET", notes_url, None),
        ("PUT", notes_url, notes_body),
        ("GET", course + "/jobs", None),
    ]
    other = TestClient(app, headers={"Origin": ORIGIN})  # no lifespan: keep the job pool open
    assert register(other, "other@example.com").status_code == 201
    student, _ = make_student(other, app, "kid@example.com")
    admin = TestClient(app, headers={"Origin": ORIGIN})
    assert login(admin, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    for method, path, body in paths:
        assert other.request(method, path, json=body).status_code == 404, path
        assert student.request(method, path, json=body).status_code == 403, path
        assert admin.request(method, path, json=body).status_code == 403, path
        assert anonymous.request(method, path, json=body).status_code == 401, path
