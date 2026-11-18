"""Part B: student portal, exam-prep coach, quizzes, study aids, and narrated-slides video."""

import io
import subprocess
import wave
from uuid import UUID

import imageio_ffmpeg
import pytest
from conftest import ORIGIN, approved, register, wait
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_accounts import make_student

from app.models.entities import ChatMessage, SourceChunk, StudyAid, Video
from app.services import citations
from app.services.student_tools import NOT_COVERED
from app.services.video import video_path

S = "/api/v1/student"


@pytest.fixture
def published(course, signed_in, app):
    """A published course (3 units, notes, concept graph) and one of the teacher's students."""
    approved(signed_in, app, course)
    wait(app, signed_in.post(course + "/notes/generate", json={}))
    wait(app, signed_in.post(course + "/concepts/build"))
    assert signed_in.post(course + "/publish").status_code == 200
    student, _ = make_student(signed_in, app, "kid@example.com")
    course_id = course.rsplit("/", 1)[1]
    detail = student.get(f"{S}/courses/{course_id}").json()
    return {
        "teacher": signed_in,
        "student": student,
        "base": course,
        "id": course_id,
        "detail": detail,
    }


def chunk_labels(app) -> set[str]:
    with app.state.session_factory() as db:
        return {f"C{o}" for o in db.scalars(select(SourceChunk.ordinal))}


def counting(app, schema):
    """Wrap a demo builder to count model calls."""
    calls = []
    original = app.state.ai.structured_builders[schema]

    def wrapped(instructions, prompt):
        calls.append(prompt)
        return original(instructions, prompt)

    app.state.ai.structured_builders[schema] = wrapped
    return calls


def drain(app):
    for future in list(app.state.jobs.futures.values()):
        future.result(timeout=120)


# ---- portal ---------------------------------------------------------------------------------


def test_portal_lists_syllabus_notes_progress_and_export(published, app):
    student, url = published["student"], f"{S}/courses/{published['id']}"
    detail = published["detail"]
    assert detail["course"]["title"] == "Ecosystems" and detail["course"]["units_total"] == 3
    units = detail["units"]
    assert len(units) == 3 and all(u["has_notes"] and not u["has_lab_manual"] for u in units)
    unit = units[0]
    notes = student.get(f"{url}/units/{unit['id']}/notes").json()
    assert notes["version"] == 1 and notes["markdown"].startswith("# Unit 1")
    assert set(citations.markers(notes["markdown"])) == set(notes["citations"])
    assert student.get(f"{url}/units/{unit['id']}/lab").status_code == 404

    progress = f"{url}/units/{unit['id']}/progress"
    assert student.put(progress).status_code == 204 and student.put(progress).status_code == 204
    assert student.get(url).json()["course"]["units_done"] == 1
    assert student.get(url).json()["units"][0]["studied"] is True
    assert student.delete(progress).status_code == 204
    assert student.get(url).json()["course"]["units_done"] == 0

    md = student.get(f"{url}/export", params={"format": "md"})
    assert md.status_code == 200 and "### Sources for this unit" in md.text
    pdf = student.get(f"{url}/export", params={"format": "pdf"})
    assert pdf.content.startswith(b"%PDF")


def test_students_see_the_published_snapshot_only(published, app):
    teacher, student, base = published["teacher"], published["student"], published["base"]
    unit_id = published["detail"]["units"][0]["id"]
    artifact = teacher.get(base + "/notes").json()[0]["artifact_id"]
    draft = "# Draft\n\n## Secret\n\nNot ready yet [C1]."
    teacher.put(f"{base}/notes/{artifact}", json={"markdown": draft, "expected_version": 1})
    notes_url = f"{S}/courses/{published['id']}/units/{unit_id}/notes"
    assert "Secret" not in student.get(notes_url).json()["markdown"]
    assert "Secret" not in student.get(f"{S}/courses/{published['id']}/export").text
    teacher.post(base + "/publish")
    assert student.get(notes_url).json()["version"] == 2
    teacher.post(base + "/unpublish")
    assert student.get(notes_url).status_code == 404
    assert student.get(f"{S}/courses/{published['id']}").status_code == 404


def test_portal_access_rules(published, app):
    url = f"{S}/courses/{published['id']}"
    unit = published["detail"]["units"][0]["id"]
    other_teacher = TestClient(app, headers={"Origin": ORIGIN})
    assert register(other_teacher, "t2@example.com").status_code == 201
    stranger, _ = make_student(other_teacher, app, "stranger@example.com")
    paths = [url, f"{url}/units/{unit}/notes", f"{url}/coach", f"{url}/quizzes", f"{url}/export"]
    for path in paths:
        assert stranger.get(path).status_code == 404, path
        assert published["teacher"].get(path).status_code == 403, path
        assert TestClient(app, headers={"Origin": ORIGIN}).get(path).status_code == 401, path
    assert stranger.get(f"{S}/courses").json() == []


# ---- coach ----------------------------------------------------------------------------------


def test_coach_finds_gaps_with_citations_and_keeps_history(published, app):
    student, url = published["student"], f"{S}/courses/{published['id']}/coach"
    graph = published["teacher"].get(published["base"] + "/concepts").json()["concepts"]
    first, second = graph[0]["name"], graph[1]["name"]
    turn = student.post(url, json={"message": f"I know {first}, what else do I need?"})
    assert turn.status_code == 200, turn.text
    reply = turn.json()["reply"]
    assert reply["in_scope"] is True and reply["known"] == [first]
    used = set(citations.markers(reply["content"] + str(reply["checklist"])))
    assert used and used <= set(reply["citations"]) <= chunk_labels(app)
    items = [c["item"] for c in reply["checklist"]]
    assert first not in items and items[0] == second  # next step comes first

    generic = student.post(url, json={"message": "What should I study next?"}).json()["reply"]
    assert generic["in_scope"] is True
    # Known concepts accumulate across the conversation.
    assert generic["known"] == [first]

    history = student.get(url).json()
    assert [m["role"] for m in history] == ["student", "coach"] * 2
    assert history[0]["content"].startswith("I know")
    assert student.delete(url).status_code == 204 and student.get(url).json() == []
    with app.state.session_factory() as db:
        assert db.scalars(select(ChatMessage)).all() == []


def test_coach_refuses_out_of_scope_without_calling_the_model(published, app):
    calls = counting(app, "CoachReply")
    url = f"{S}/courses/{published['id']}/coach"
    reply = published["student"].post(url, json={"message": "What is the capital of France?"})
    body = reply.json()["reply"]
    assert body["in_scope"] is False and body["content"].startswith(NOT_COVERED)
    assert body["citations"] == {} and body["checklist"] == [] and calls == []

    # The model itself may also decline.
    app.state.ai.structured_builders["CoachReply"] = lambda i, p: {
        "in_scope": False,
        "answer": "Paris",
        "checklist": [],
    }
    declined = published["student"].post(url, json={"message": "Explain glucose and light"})
    assert declined.json()["reply"]["content"].startswith(NOT_COVERED)
    assert "Paris" not in declined.text


def test_coach_never_returns_invented_citations(published, app):
    calls = []

    def inventing(instructions, prompt):
        calls.append(prompt)
        return {"in_scope": True, "answer": "Trust me [C999].", "checklist": []}

    app.state.ai.structured_builders["CoachReply"] = inventing
    url = f"{S}/courses/{published['id']}/coach"
    reply = published["student"].post(url, json={"message": "Tell me about mitochondria"})
    body = reply.json()["reply"]
    assert len(calls) == 2 and "C999" not in body["content"]
    assert set(body["citations"]) <= chunk_labels(app) and body["citations"]
    assert body["checklist"]  # falls back to the concept order


# ---- quizzes --------------------------------------------------------------------------------


def test_quiz_generate_hide_answers_grade_and_store(published, app):
    student, url = published["student"], f"{S}/courses/{published['id']}/quizzes"
    unit = published["detail"]["units"][0]["id"]
    made = student.post(url, json={"unit_id": unit, "difficulty": "easy", "count": 3})
    assert made.status_code == 201, made.text
    quiz = made.json()
    assert quiz["difficulty"] == "easy" and quiz["total"] >= 1 and quiz["score"] is None
    for q in quiz["questions"]:
        assert len(q["options"]) == 4 and q["answer_index"] is None and q["explanation"] is None
    with app.state.session_factory() as db:
        from app.models.entities import Quiz

        stored = db.get(Quiz, UUID(quiz["id"]))
        correct = [q["answer_index"] for q in stored.questions]
    answers = [correct[0]] + [(c + 1) % 4 for c in correct[1:]]
    submit = f"{S}/quizzes/{quiz['id']}/submit"
    assert student.post(submit, json={"answers": answers[:-1] or [None, None]}).status_code == 422
    graded = student.post(submit, json={"answers": answers}).json()
    assert graded["score"] == 1 and graded["questions"][0]["correct"] is True
    assert graded["questions"][0]["explanation"] and graded["questions"][0]["sources"]
    assert student.post(submit, json={"answers": answers}).status_code == 409
    history = student.get(url).json()
    assert history[0]["score"] == 1 and history[0]["total"] == quiz["total"]
    other, _ = make_student(published["teacher"], app, "other@example.com")
    assert other.get(f"{S}/quizzes/{quiz['id']}").status_code == 404


def test_invalid_quiz_questions_are_dropped(published, app):
    url = f"{S}/courses/{published['id']}/quizzes"
    good = {"question": "Q?", "options": ["a", "b", "c", "d"], "answer_index": 1}
    bad_cite = good | {"explanation": "Because [C999]."}
    three = good | {"options": ["a", "b", "c"], "explanation": "x [C1]"}
    dup = good | {"options": ["a", "a", "c", "d"], "explanation": "x [C1]"}
    out_of_range = good | {"answer_index": 4, "explanation": "x [C1]"}
    app.state.ai.structured_builders["QuizDraft"] = lambda i, p: {
        "questions": [bad_cite, three, dup, out_of_range]
    }
    assert published["student"].post(url, json={"count": 3}).status_code == 502
    valid = good | {"explanation": "Because [C1]."}
    app.state.ai.structured_builders["QuizDraft"] = lambda i, p: {"questions": [bad_cite, valid]}
    quiz = published["student"].post(url, json={"count": 3}).json()
    assert quiz["total"] == 1


# ---- study aids -----------------------------------------------------------------------------


def test_study_aids_are_grounded_and_cached(published, app):
    student, teacher = published["student"], published["teacher"]
    unit = published["detail"]["units"][0]["id"]
    base = f"{S}/courses/{published['id']}/units/{unit}/aids"
    notes = student.get(f"{S}/courses/{published['id']}/units/{unit}/notes").json()
    mind = student.post(base + "/mind_map").json()
    assert mind["content"]["central"] and mind["content"]["branches"]
    assert all(b["label"] and b["children"] for b in mind["content"]["branches"])
    short = student.post(base + "/short_notes").json()
    assert short["content"]["points"]
    assert set(citations.markers(str(short["content"]))) <= set(notes["citations"])
    cards = student.post(base + "/flashcards").json()
    assert cards["content"]["cards"] and all(
        c["front"] and c["back"] for c in cards["content"]["cards"]
    )
    assert student.post(base + "/poems").status_code == 422

    calls = counting(app, "MindMapDraft")
    assert student.post(base + "/mind_map").json() == mind and calls == []  # cached
    artifact = teacher.get(published["base"] + "/notes").json()[0]["artifact_id"]
    teacher.put(
        f"{published['base']}/notes/{artifact}",
        json={"markdown": "# U\n\n## New idea\n\nFresh text here [C1].", "expected_version": 1},
    )
    teacher.post(published["base"] + "/publish")
    fresh = student.post(base + "/mind_map").json()
    assert fresh["notes_version"] == 2 and len(calls) == 1
    with app.state.session_factory() as db:
        assert len(db.scalars(select(StudyAid).where(StudyAid.tool == "mind_map")).all()) == 2


# ---- video ----------------------------------------------------------------------------------


def probe(path) -> str:
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    return result.stderr


def tone_wav(seconds=0.4, rate=16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x10\x00\xf0\xff" * int(seconds * rate / 2))
    return buffer.getvalue()


def make_video(published, app):
    unit = published["detail"]["units"][0]["id"]
    url = f"{S}/courses/{published['id']}/units/{unit}/video"
    student = published["student"]
    assert student.get(url).json()["status"] == "none"
    started = student.post(url)
    assert started.status_code == 202 and started.json()["status"] == "queued"
    drain(app)
    return url, student.get(url).json()


def test_demo_video_is_silent_with_captions(published, app):
    url, status = make_video(published, app)
    assert status["status"] == "ready", status
    assert status["has_audio"] is False and "captions" in status["message"]
    assert status["slide_count"] >= 2 and status["duration_seconds"] > 2
    file = published["student"].get(url + "/file")
    assert file.status_code == 200 and file.headers["content-type"] == "video/mp4"
    assert file.content[4:8] == b"ftyp"
    with app.state.session_factory() as db:
        video = db.scalar(select(Video))
        path = video_path(app.state.settings, video.storage_key)
    info = probe(path)
    assert "Video: h264" in info and "Audio:" not in info
    # A second request reuses the ready video instead of starting a new job.
    assert published["student"].post(url).json()["status"] == "ready"
    with app.state.session_factory() as db:
        assert len(db.scalars(select(Video)).all()) == 1
    # Deleting the course removes the video file too.
    assert published["teacher"].delete(published["base"]).status_code == 204
    assert not path.exists()


def test_video_with_narration_has_an_audio_track(published, app):
    spoken = []
    app.state.ai.speech = lambda text: spoken.append(text) or tone_wav()
    url, status = make_video(published, app)
    assert status["status"] == "ready" and status["has_audio"] is True
    assert status["message"] is None and spoken and "[C" not in " ".join(spoken)
    with app.state.session_factory() as db:
        path = video_path(app.state.settings, db.scalar(select(Video)).storage_key)
    info = probe(path)
    assert "Video: h264" in info and "Audio: aac" in info


def test_video_failure_is_reported(published, app):
    app.state.ai.structured_builders["VideoScript"] = lambda i, p: {"slides": []}
    url, status = make_video(published, app)
    assert status["status"] == "failed" and "empty video script" in status["message"]
    assert published["student"].get(url + "/file").status_code == 404
    # Retrying after a failure starts a new attempt.
    del app.state.ai.structured_builders["VideoScript"]
    from app.services.demo_ai import install

    install(app.state.ai)
    published["student"].post(url)
    drain(app)
    assert published["student"].get(url).json()["status"] == "ready"
