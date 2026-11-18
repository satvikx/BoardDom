"""Course wizard: validated plan stored per course; the syllabus generator follows it."""

import pytest
from conftest import ORIGIN, extracted_source, register, wait
from fastapi.testclient import TestClient

from app.services.course_content import UnitDraft, apply_profile

API = "/api/v1/workspaces"
PLAN = {
    "audience": "Year 10 science",
    "weeks": 9,
    "hours_per_week": 3,
    "mode": "theory_lab",
    "lab_hours_per_week": 2,
    "experiments": 4,
    "must_include": ["Enzymes", "Food chains"],
    "exclude": ["Respiration"],
    "assessment": [
        {"name": "Quizzes", "weight_percent": 20},
        {"name": "Lab reports", "weight_percent": 30},
        {"name": "Final exam", "weight_percent": 50},
    ],
}
WIZARD = {"title": "Energy", "subject": "Biology", "learner_level": "intermediate", "profile": PLAN}


def test_wizard_creates_course_and_plan(signed_in):
    made = signed_in.post(API + "/wizard", json=WIZARD)
    assert made.status_code == 201, made.text
    course = made.json()
    assert course["has_lab"] is True and course["learner_level"] == "intermediate"
    profile = signed_in.get(f"{API}/{course['id']}/profile").json()
    assert profile["weeks"] == 9 and profile["must_include"] == ["Enzymes", "Food chains"]
    assert [a["name"] for a in profile["assessment"]] == ["Quizzes", "Lab reports", "Final exam"]

    theory = PLAN | {"mode": "theory", "lab_hours_per_week": 0, "experiments": 0}
    updated = signed_in.put(f"{API}/{course['id']}/profile", json=theory)
    assert updated.status_code == 200 and updated.json()["mode"] == "theory"
    assert signed_in.get(f"{API}/{course['id']}").json()["has_lab"] is False
    plain = signed_in.post(API, json={"title": "No plan"}).json()
    assert signed_in.get(f"{API}/{plain['id']}/profile").json() is None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"weeks": 0}, "weeks"),
        ({"weeks": 60}, "weeks"),
        ({"hours_per_week": 1.5}, "hours_per_week"),
        ({"mode": "theory_lab", "lab_hours_per_week": 0}, "needs lab hours"),
        ({"mode": "theory", "lab_hours_per_week": 2, "experiments": 0}, "only to theory + lab"),
        ({"must_include": ["Cells"], "exclude": ["cells"]}, "both required and excluded"),
        ({"assessment": [{"name": "Exam", "weight_percent": 90}]}, "add up to 100%"),
        ({"assessment": []}, "assessment"),
        (
            {
                "assessment": [
                    {"name": "A", "weight_percent": 50},
                    {"name": "a", "weight_percent": 50},
                ]
            },
            "different name",
        ),
        ({"audience": "  "}, "audience"),
        ({"must_include": ["x" * 101]}, "must_include"),
    ],
)
def test_wizard_rejects_invalid_plans(signed_in, change, message):
    result = signed_in.post(API + "/wizard", json=WIZARD | {"profile": PLAN | change})
    assert result.status_code == 422 and message in result.json()["detail"]


def test_wizard_requires_subject_and_teacher(signed_in, app):
    assert signed_in.post(API + "/wizard", json=WIZARD | {"subject": " "}).status_code == 422
    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    assert anonymous.post(API + "/wizard", json=WIZARD).status_code == 401
    course = signed_in.post(API + "/wizard", json=WIZARD).json()
    other = TestClient(app, headers={"Origin": ORIGIN})
    register(other, "other@example.com")
    assert other.get(f"{API}/{course['id']}/profile").status_code == 404
    assert other.put(f"{API}/{course['id']}/profile", json=PLAN).status_code == 404


def test_apply_profile_enforces_the_plan():
    class Plan:
        weeks, must_include, exclude = 10, ["Enzymes", "Energy flow"], ["Respiration"]

    units = [
        UnitDraft(
            title="Photosynthesis", summary="", topics=["Light", "Enzymes"], weeks=2, sources=[]
        ),
        UnitDraft(title="Respiration", summary="", topics=["ATP"], weeks=2, sources=[]),
        UnitDraft(
            title="Food chains",
            summary="",
            topics=["Energy", "Respiration in animals"],
            weeks=1,
            sources=[],
        ),
    ]
    kept, notes = apply_profile(units, Plan)
    assert [u.title for u in kept] == ["Photosynthesis", "Food chains"]
    assert "Respiration in animals" not in kept[1].topics
    assert "Energy flow" in kept[1].topics  # added where it overlaps most ("Energy")
    assert sum(u.weeks for u in kept) == 10 and all(u.weeks >= 1 for u in kept)
    assert any("added required topic" in n for n in notes)
    assert any("excluded" in n for n in notes)


def test_syllabus_and_rubric_follow_the_wizard(signed_in, app):
    course = signed_in.post(API + "/wizard", json=WIZARD).json()
    base = f"{API}/{course['id']}"
    extracted_source(app, base, signed_in)
    prompts = []
    original = app.state.ai.structured_builders["SyllabusDraft"]
    app.state.ai.structured_builders["SyllabusDraft"] = lambda i, p: (
        prompts.append(p) or original(i, p)
    )
    job = wait(app, signed_in.post(base + "/syllabus/generate"))
    assert (
        "Length: 9 weeks" in prompts[0]
        and "Must include topics: Enzymes; Food chains" in prompts[0]
    )
    assert "Exclude topics: Respiration" in prompts[0] and "Lab experiments: 4" in prompts[0]
    assert "Adjusted:" in job.message and "excluded" in job.message
    syllabus = signed_in.get(base + "/syllabus").json()
    text = " ".join(f"{u['title']} {' '.join(u['topics'])}" for u in syllabus["units"])
    assert "Enzymes" in text and "Food chains" in text and "Respiration" not in text
    assert sum(u["weeks"] for u in syllabus["units"]) == 9
    assert all(
        u["citations"] and all(k.startswith("C") for k in u["citations"]) for u in syllabus["units"]
    )

    approved = signed_in.post(
        base + "/syllabus/approve", json={"expected_revision": syllabus["revision"]}
    )
    assert approved.status_code == 200
    wait(app, signed_in.post(base + "/artifacts/generate", json={"kind": "rubric"}))
    rows = signed_in.get(base + "/artifacts", params={"kind": "rubric"}).json()
    rubric = signed_in.get(f"{base}/artifacts/{rows[0]['artifact_id']}").json()["markdown"]
    for line in ("| Quizzes | 20% |", "| Lab reports | 30% |", "| Final exam | 50% |"):
        assert line in rubric

    reopened = signed_in.post(
        base + "/syllabus/reopen", json={"expected_revision": approved.json()["revision"]}
    ).json()
    unit = reopened["units"][0]
    edited = signed_in.put(
        base + "/syllabus",
        json={
            "expected_revision": reopened["revision"],
            "units": [{"id": unit["id"], "title": unit["title"], "weeks": 3}],
        },
    )
    assert edited.json()["units"][0]["weeks"] == 3
    assert edited.json()["units"][0]["citations"] == unit["citations"]  # kept on edit
