"""Part A: lab manuals, lesson plans, rubric, concept graph, publishing and export."""

from alembic.config import Config
from conftest import approved, wait
from sqlalchemy import func, select, text

from alembic import command
from app.core.config import BACKEND_ROOT
from app.models.entities import Artifact, Concept, ConceptEdge
from app.services import citations
from app.services.concepts import (
    ConceptGraphDraft,
    clean_graph,
    known_concepts,
    load_graph,
    prioritize,
)


def generate(client, app, base, kind, unit_ids=None, expect="succeeded"):
    body = {"kind": kind} | ({"unit_ids": unit_ids} if unit_ids else {})
    return wait(app, client.post(base + "/artifacts/generate", json=body), expect)


def artifact(client, base, kind, index=0):
    rows = client.get(base + "/artifacts", params={"kind": kind}).json()
    return client.get(f"{base}/artifacts/{rows[index]['artifact_id']}").json()


# ---- workspace lab flag ---------------------------------------------------------------------


def test_has_lab_flag_on_courses(signed_in):
    created = signed_in.post("/api/v1/workspaces", json={"title": "Chem", "has_lab": True})
    assert created.status_code == 201 and created.json()["has_lab"] is True
    assert created.json()["published_at"] is None
    url = f"/api/v1/workspaces/{created.json()['id']}"
    assert signed_in.patch(url, json={"has_lab": False}).json()["has_lab"] is False
    assert signed_in.patch(url, json={"has_lab": None}).status_code == 422
    default = signed_in.post("/api/v1/workspaces", json={"title": "Plain"}).json()
    assert default["has_lab"] is False


# ---- lab manuals ----------------------------------------------------------------------------


def test_lab_manuals_need_a_lab_then_generate_with_citations(course, signed_in, app):
    approved(signed_in, app, course)
    blocked = signed_in.post(course + "/artifacts/generate", json={"kind": "lab_manual"})
    assert blocked.status_code == 409 and "no lab" in blocked.json()["detail"]
    signed_in.patch(course, json={"has_lab": True})
    job = generate(signed_in, app, course, "lab_manual")
    assert job.message == "Generated lab manuals for 3 of 3 unit(s)."
    lab = artifact(signed_in, course, "lab_manual")
    md = lab["markdown"]
    for heading in ("## Aim", "## Apparatus", "## Procedure", "## Observation table", "## Viva"):
        assert heading in md
    assert "| No. | Trial | Observation | Measurement | Remarks |" in md
    assert md.count("\n| ") >= 6 and "1. Put on safety glasses" in md
    used = set(citations.markers(md))
    assert used and used == set(lab["citations"]) and lab["kind"] == "lab_manual"

    # Edit and regenerate keep history, like notes.
    url = f"{course}/artifacts/{lab['artifact_id']}"
    bad = signed_in.put(url, json={"markdown": "## Aim\n\nx [C77]", "expected_version": 1})
    assert bad.status_code == 422
    edited = signed_in.put(url, json={"markdown": md + "\nExtra [C1].\n", "expected_version": 1})
    assert edited.status_code == 200 and edited.json()["number"] == 2
    generate(signed_in, app, course, "lab_manual", [lab["unit_id"]])
    assert [v["origin"] for v in signed_in.get(url).json()["versions"]] == [
        "generated",
        "edited",
        "generated",
    ]
    # Notes endpoints only serve notes.
    assert signed_in.get(f"{course}/notes/{lab['artifact_id']}").status_code == 404


# ---- lesson plans and rubric ----------------------------------------------------------------


def test_lesson_plans_fit_the_session_length(course, signed_in, app):
    signed_in.patch(course, json={"lesson_duration_minutes": 50})
    approved(signed_in, app, course)
    job = generate(signed_in, app, course, "lesson_plan")
    assert "3 of 3" in job.message
    plan = artifact(signed_in, course, "lesson_plan", 1)
    assert "## Session 1:" in plan["markdown"] and "(50 minutes)" in plan["markdown"]
    assert "| Minutes | Activity |" in plan["markdown"] and plan["warnings"] == []

    # A plan whose minutes do not add up is kept, with a warning; citations are optional.
    app.state.ai.structured_builders["LessonPlanDraft"] = lambda i, p: {
        "sessions": [
            {
                "title": "Too long",
                "objectives": ["o"],
                "activities": [{"minutes": 45, "activity": "a"}, {"minutes": 30, "activity": "b"}],
                "assessment": "quiz",
            }
        ]
    }
    generate(signed_in, app, course, "lesson_plan", [plan["unit_id"]])
    latest = artifact(signed_in, course, "lesson_plan", 1)
    assert latest["number"] == 2 and latest["warnings"] == ["Session 1 plans 75 of 50 minutes."]


def test_rubric_is_one_course_level_artifact(course, signed_in, app):
    approved(signed_in, app, course)
    bad = signed_in.post(
        course + "/artifacts/generate",
        json={"kind": "rubric", "unit_ids": ["00000000-0000-0000-0000-000000000001"]},
    )
    assert bad.status_code == 422
    assert generate(signed_in, app, course, "rubric").message == "Generated the assessment rubric."
    generate(signed_in, app, course, "rubric")
    rows = signed_in.get(course + "/artifacts", params={"kind": "rubric"}).json()
    assert len(rows) == 1 and rows[0]["unit_id"] is None and rows[0]["current_version"] == 2
    rubric = artifact(signed_in, course, "rubric")
    assert rubric["markdown"].startswith("# Assessment rubric: Ecosystems")
    assert "| Criterion | Weight |" in rubric["markdown"] and rubric["warnings"] == []
    with app.state.session_factory() as db:
        count = select(func.count()).select_from(Artifact).where(Artifact.kind == "rubric")
        assert db.scalar(count) == 1
    assert signed_in.get(course + "/artifacts", params={"kind": "poem"}).status_code == 404


# ---- concept graph --------------------------------------------------------------------------


def test_clean_graph_drops_bad_edges_and_cycles():
    draft = ConceptGraphDraft.model_validate(
        {
            "concepts": [
                {"name": "Light", "description": "", "unit_title": "U1"},
                {"name": "light ", "description": "dup", "unit_title": "U1"},
                {"name": "Photosynthesis", "description": "", "unit_title": "U1"},
                {"name": "Glucose", "description": "", "unit_title": "U2"},
            ],
            "edges": [
                {"prerequisite": "Light", "concept": "Photosynthesis"},
                {"prerequisite": "Photosynthesis", "concept": "Glucose"},
                {"prerequisite": "Glucose", "concept": "Light"},  # closes a cycle
                {"prerequisite": "Light", "concept": "Light"},  # self loop
                {"prerequisite": "Magic", "concept": "Light"},  # unknown
                {"prerequisite": "light", "concept": "photosynthesis"},  # duplicate
            ],
        }
    )
    concepts, edges, dropped = clean_graph(draft)
    assert [c.name for c in concepts] == ["Light", "Photosynthesis", "Glucose"]
    assert edges == [("light", "photosynthesis"), ("photosynthesis", "glucose")]
    assert dropped == 4


def test_concept_graph_build_view_and_gap_order(course, signed_in, app):
    assert signed_in.post(course + "/concepts/build").status_code == 409
    approved(signed_in, app, course)
    wait(app, signed_in.post(course + "/notes/generate", json={}))
    job = wait(app, signed_in.post(course + "/concepts/build"))
    assert job.message == "Mapped 3 concepts and 2 prerequisite links."
    graph = signed_in.get(course + "/concepts").json()
    assert graph["edge_count"] == 2
    assert [c["level"] for c in graph["concepts"]] == [0, 1, 2]
    assert all(c["unit_title"] for c in graph["concepts"])
    first, second = graph["concepts"][:2]
    assert second["prerequisite_ids"] == [first["id"]]

    with app.state.session_factory() as db:
        workspace_id = db.scalar(select(Concept.workspace_id))
        concepts, edges = load_graph(db, workspace_id)
        by_name = {c.name: c for c in concepts}
        names = [c.name for c in concepts]
        known = known_concepts(f"I already know {names[0].upper()} well", concepts)
        assert known == {by_name[names[0]].id}
        assert [c.name for c in prioritize(concepts, edges, known)] == names[1:]
        assert [c.name for c in prioritize(concepts, edges, set())] == names
    # Rebuilding replaces the graph instead of duplicating it.
    wait(app, signed_in.post(course + "/concepts/build"))
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Concept)) == 3
        assert db.scalar(select(func.count()).select_from(ConceptEdge)) == 2


# ---- publishing and export ------------------------------------------------------------------


def test_publish_snapshot_unpublish_and_export(course, signed_in, app):
    assert signed_in.post(course + "/publish").status_code == 409  # no approved syllabus
    approved(signed_in, app, course)
    nothing = signed_in.post(course + "/publish")
    assert nothing.status_code == 409 and "notes" in nothing.json()["detail"]
    wait(app, signed_in.post(course + "/notes/generate", json={}))
    published = signed_in.post(course + "/publish")
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["published_at"] and body["unpublished_changes"] is False
    assert all(u["notes_published"] == 1 for u in body["units"])
    assert signed_in.get(course).json()["published_at"]

    notes = signed_in.get(course + "/notes").json()[0]
    url = f"{course}/notes/{notes['artifact_id']}"
    signed_in.put(
        url, json={"markdown": "# Draft\n\n## New\n\nUnreleased [C1].", "expected_version": 1}
    )
    status = signed_in.get(course + "/publication").json()
    assert status["unpublished_changes"] is True
    assert status["units"][0]["notes_current"] == 2 and status["units"][0]["notes_published"] == 1

    current = signed_in.get(course + "/export", params={"format": "md"})
    assert current.headers["content-disposition"].endswith("Ecosystems.md")
    assert "Unreleased [C1]" in current.text and current.text.startswith("# Ecosystems")
    assert "### Sources for this unit" in current.text and "notes.md, page" in current.text
    released = signed_in.get(course + "/export", params={"format": "md", "which": "published"})
    assert "Unreleased" not in released.text and "## Syllabus" in released.text
    pdf = signed_in.get(course + "/export", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-type"] == "application/pdf" and len(pdf.content) > 1000
    assert signed_in.get(course + "/export", params={"format": "doc"}).status_code == 422

    off = signed_in.post(course + "/unpublish").json()
    assert off["published_at"] is None and signed_in.get(course).json()["published_at"] is None


def test_pdf_handles_unicode_and_tables():
    from app.services.publishing import export_pdf

    md = (
        "# Énergie “quotes” — 🌱\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n- **bold** item\n1. step"
    )
    assert export_pdf(md, "Title").startswith(b"%PDF")


# ---- migration ------------------------------------------------------------------------------


def test_part_a_migration_keeps_course_data(tmp_path):
    from app.db.session import build_engine

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    url = f"sqlite:///{tmp_path / 'm.db'}"
    config.attributes["database_url"] = url
    command.upgrade(config, "e5a7c2d9b4f1")
    engine = build_engine(url)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO users (id,email,display_name,password_hash,created_at,updated_at,"
                "role,must_change_password) VALUES (:id,'t@example.com','T','h',"
                "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'teacher',0)"
            ),
            {"id": "1" * 32},
        )
        db.execute(
            text(
                "INSERT INTO workspaces VALUES (:id,:o,'Lesson',NULL,NULL,'introductory',40,"
                "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": "2" * 32, "o": "1" * 32},
        )
        db.execute(
            text(
                "INSERT INTO artifacts VALUES "
                "(:id,:w,'unit_notes',NULL,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": "3" * 32, "w": "2" * 32},
        )
        db.execute(
            text(
                "INSERT INTO jobs VALUES "
                "(:id,:w,'notes','succeeded',1,1,NULL,NULL,CURRENT_TIMESTAMP,NULL)"
            ),
            {"id": "4" * 32, "w": "2" * 32},
        )
    command.upgrade(config, "head")
    with engine.connect() as db:
        counts = [
            db.execute(text(f"SELECT count(*) FROM {t}")).scalar()
            for t in ("workspaces", "artifacts", "jobs")
        ]
        assert counts == [1, 1, 1]
        assert db.execute(text("SELECT has_lab, published_at FROM workspaces")).one() == (0, None)
    command.check(config)
    command.downgrade(config, "e5a7c2d9b4f1")
    with engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM artifacts")).scalar() == 1
    engine.dispose()
