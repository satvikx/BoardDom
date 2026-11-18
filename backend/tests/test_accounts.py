from uuid import UUID

import pytest
from alembic.config import Config
from conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    ADMIN_PIN,
    ORIGIN,
    approved,
    extracted_source,
    make_settings,
    upload,
    wait,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, text

from alembic import command
from app.core.config import BACKEND_ROOT, Settings
from app.core.ratelimit import FailureLimiter
from app.core.security import password_hasher
from app.main import create_app
from app.models.entities import Enrollment, SessionToken, SourceDocument, User, Workspace

API = "/api/v1"
NEW_PASSWORD = "brand-new-password"
NIL = "00000000-0000-0000-0000-000000000001"


def new_client(app):
    # No context manager: the fixture client already ran startup (admin seeding).
    return TestClient(app, headers={"Origin": ORIGIN})


def login(c, email, password):
    return c.post(f"{API}/auth/login", json={"email": email, "password": password})


@pytest.fixture
def admin(client):
    assert login(client, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    return client


def activate(app, email, temporary, new=NEW_PASSWORD):
    c = new_client(app)
    result = login(c, email, temporary)
    assert result.status_code == 200, result.text
    assert result.json()["must_change_password"] is True
    changed = c.post(
        f"{API}/auth/change-password",
        json={"current_password": temporary, "new_password": new},
    )
    assert changed.status_code == 200, changed.text
    return c


def make_teacher(admin, app, email="teacher1@example.com", **extra):
    result = admin.post(
        f"{API}/admin/teachers", json={"display_name": "Tess Teacher", "email": email, **extra}
    )
    assert result.status_code == 201, result.text
    body = result.json()
    return activate(app, email, body["temporary_password"]), body["user"]["id"]


def add_student(teacher, email):
    return teacher.post(
        f"{API}/teacher/students", json={"display_name": f"Student {email[:3]}", "email": email}
    )


def make_student(teacher, app, email="student1@example.com"):
    result = add_student(teacher, email)
    assert result.status_code == 201, result.text
    body = result.json()
    return activate(app, email, body["temporary_password"]), body["student"]["id"]


def make_course(teacher, title="Ecosystems"):
    result = teacher.post(f"{API}/workspaces", json={"title": title, "subject": "Biology"})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def migrate(tmp_path, revision="head"):
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = f"sqlite:///{tmp_path / 'test.db'}"
    command.upgrade(config, revision)
    return config


# --- Admin seeding and configuration -------------------------------------------------


def test_admin_seeded_once_and_not_overwritten_on_restart(tmp_path):
    migrate(tmp_path)
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings), headers={"Origin": ORIGIN}) as c:
        me = login(c, ADMIN_EMAIL, ADMIN_PASSWORD)
        assert me.status_code == 200 and me.json()["role"] == "admin"
        assert me.json()["must_change_password"] is False
        assert (
            c.post(
                f"{API}/auth/change-password",
                json={"current_password": ADMIN_PASSWORD, "new_password": NEW_PASSWORD},
            ).status_code
            == 200
        )
    restarted = create_app(make_settings(tmp_path))
    with TestClient(restarted, headers={"Origin": ORIGIN}) as c:
        assert login(c, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 401
        assert login(c, ADMIN_EMAIL, NEW_PASSWORD).status_code == 200
    with restarted.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) == 1


def test_production_refuses_default_admin_secrets():
    base = dict(_env_file=None, environment="production")
    with pytest.raises(ValidationError, match="default admin password or reset PIN"):
        Settings(**base, admin_reset_pin="913372")
    with pytest.raises(ValidationError, match="default admin password or reset PIN"):
        Settings(**base, admin_password="a-strong-secret")
    ok = Settings(**base, admin_password="a-strong-secret", admin_reset_pin="913372")
    assert ok.environment == "production"
    # Development keeps working defaults so `cp .env.example .env` is enough.
    assert Settings(_env_file=None).admin_email == "admin@example.com"


def test_public_signup_off_returns_403(tmp_path):
    migrate(tmp_path)
    app = create_app(make_settings(tmp_path).model_copy(update={"allow_public_signup": False}))
    with TestClient(app, headers={"Origin": ORIGIN}) as c:
        assert c.get(f"{API}/config").json()["allow_public_signup"] is False
        result = c.post(
            f"{API}/auth/register",
            json={"email": "x@example.com", "display_name": "X", "password": "long-password"},
        )
        assert result.status_code == 403
        assert "sign-up is turned off" in result.json()["detail"]


def test_public_signup_creates_teacher(client):
    result = client.post(
        f"{API}/auth/register",
        json={"email": "self@example.com", "display_name": "Self", "password": "long-password"},
    )
    assert result.status_code == 201 and result.json()["role"] == "teacher"
    assert client.get(f"{API}/workspaces").status_code == 200


# --- Role checks ---------------------------------------------------------------------


def test_role_checks_on_every_route(admin, app):
    teacher, teacher_id = make_teacher(admin, app)
    student, student_id = make_student(teacher, app)
    course = make_course(teacher)
    anonymous = new_client(app)
    admin_routes = [
        ("GET", "/admin/users"),
        ("POST", "/admin/teachers"),
        ("PATCH", f"/admin/teachers/{teacher_id}"),
        ("DELETE", f"/admin/users/{student_id}"),
    ]
    teacher_routes = [
        ("GET", "/teacher/students"),
        ("POST", "/teacher/students"),
        ("DELETE", f"/teacher/students/{student_id}"),
        ("GET", f"/workspaces/{course}/enrollments"),
        ("PUT", f"/workspaces/{course}/enrollments/{student_id}"),
        ("DELETE", f"/workspaces/{course}/enrollments/{student_id}"),
        ("GET", "/workspaces"),
        ("POST", "/workspaces"),
        ("GET", f"/workspaces/{course}"),
        ("PATCH", f"/workspaces/{course}"),
        ("DELETE", f"/workspaces/{course}"),
        ("GET", f"/workspaces/{course}/documents"),
        ("GET", f"/workspaces/{course}/documents/{NIL}/content"),
    ]
    student_routes = [("GET", "/student/courses")]
    body = {"title": "X", "display_name": "X", "email": "x@example.com", "student_limit": 1}
    for routes, allowed in [
        (admin_routes, "admin"),
        (teacher_routes, "teacher"),
        (student_routes, "student"),
    ]:
        for method, path in routes:
            assert anonymous.request(method, API + path, json=body).status_code == 401, path
            for role, c in [("admin", admin), ("teacher", teacher), ("student", student)]:
                if role != allowed:
                    result = c.request(method, API + path, json=body)
                    assert result.status_code == 403, (role, path, result.text)
                    assert "Not allowed" in result.json()["detail"]
    # Nothing above was actually changed by a forbidden request.
    assert teacher.get(f"{API}/workspaces/{course}").status_code == 200
    assert len(teacher.get(f"{API}/teacher/students").json()["students"]) == 1


def test_password_hash_and_temp_password_never_returned(admin, app):
    created = admin.post(
        f"{API}/admin/teachers", json={"display_name": "T", "email": "t@example.com"}
    ).json()
    temporary = created["temporary_password"]
    assert len(temporary) == 14 and temporary.count("-") == 2
    listing = admin.get(f"{API}/admin/users").text
    assert temporary not in listing and "password_hash" not in listing and "$argon2" not in listing
    assert "password_hash" not in created["user"]
    with app.state.session_factory() as db:
        stored = db.scalar(select(User).where(User.email == "t@example.com")).password_hash
        assert stored.startswith("$argon2id$") and temporary not in stored


# --- Admin PIN reset -----------------------------------------------------------------


def reset(c, pin=ADMIN_PIN, email=ADMIN_EMAIL, new=NEW_PASSWORD):
    return c.post(
        f"{API}/auth/admin/reset-password", json={"email": email, "pin": pin, "new_password": new}
    )


def test_pin_reset_success_invalidates_sessions(admin, app):
    other = new_client(app)
    assert login(other, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    with app.state.session_factory() as db:
        admin_user = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        admin_user.must_change_password = True
        db.commit()
    anonymous = new_client(app)
    assert reset(anonymous).status_code == 200
    assert admin.get(f"{API}/auth/me").status_code == 401
    assert other.get(f"{API}/auth/me").status_code == 401
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(SessionToken)) == 0
    assert login(anonymous, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 401
    me = login(anonymous, ADMIN_EMAIL, NEW_PASSWORD)
    assert me.status_code == 200 and me.json()["must_change_password"] is False


def test_pin_reset_errors_are_generic(admin, app):
    teacher_email = "teacher1@example.com"
    make_teacher(admin, app, teacher_email)
    c = new_client(app)
    wrong_pin = reset(c, pin="000000")
    unknown = reset(c, email="nobody@example.com")
    not_admin = reset(c, email=teacher_email)
    for result in (wrong_pin, unknown, not_admin):
        assert result.status_code == 400
        assert result.json() == {"detail": "Invalid PIN or account."}
    assert login(c, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    assert login(new_client(app), teacher_email, NEW_PASSWORD).status_code == 200


def test_pin_reset_lockout_after_five_failures(admin, app):
    c = new_client(app)
    for _ in range(4):
        assert reset(c, pin="111111").status_code == 400
    fifth = reset(c, email="someone@example.com")
    assert fifth.status_code == 429
    assert "PIN reset is locked" in fifth.json()["detail"]
    assert "15 minutes" in fifth.json()["detail"]
    assert int(fifth.headers["retry-after"]) == 900
    # Locked globally: even the correct PIN for the real admin is refused.
    assert reset(c).status_code == 429
    assert login(c, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200


def test_failure_limiter_window_and_expiry():
    now = [0.0]
    limiter = FailureLimiter(3, window_seconds=60, lockout_seconds=100, clock=lambda: now[0])
    limiter.record_failure("a")
    limiter.record_failure("a")
    now[0] = 61  # Earlier failures fell out of the window.
    assert limiter.record_failure("a") == 0
    assert limiter.record_failure("a") == 0
    assert limiter.record_failure("a") == 100
    assert limiter.retry_after("a") == 100 and limiter.retry_after("b") == 0
    now[0] = 161
    assert limiter.retry_after("a") == 0
    limiter.record_failure("a")
    limiter.reset("a")
    assert limiter.record_failure("a") == 0


# --- Accounts, temporary passwords, forced change ------------------------------------


def test_admin_creates_teacher_who_must_change_password(admin, app):
    result = admin.post(
        f"{API}/admin/teachers",
        json={"display_name": "Tess", "email": " Tess@Example.com ", "student_limit": 2},
    )
    assert result.status_code == 201
    body = result.json()
    assert body["user"]["email"] == "tess@example.com"
    assert body["user"]["role"] == "teacher" and body["user"]["student_limit"] == 2
    assert body["user"]["created_by_name"] == "Administrator"
    duplicate = admin.post(
        f"{API}/admin/teachers", json={"display_name": "Tess", "email": "tess@example.com"}
    )
    assert duplicate.status_code == 409

    teacher = new_client(app)
    me = login(teacher, "tess@example.com", body["temporary_password"])
    assert me.json()["must_change_password"] is True
    assert teacher.get(f"{API}/auth/me").status_code == 200
    blocked = teacher.get(f"{API}/workspaces")
    assert blocked.status_code == 403
    assert "Change your temporary password" in blocked.json()["detail"]
    assert teacher.get(f"{API}/teacher/students").status_code == 403
    wrong = teacher.post(
        f"{API}/auth/change-password",
        json={"current_password": "wrong-password", "new_password": NEW_PASSWORD},
    )
    assert wrong.status_code == 400
    same = teacher.post(
        f"{API}/auth/change-password",
        json={"current_password": body["temporary_password"], "new_password": "short"},
    )
    assert same.status_code == 422
    changed = teacher.post(
        f"{API}/auth/change-password",
        json={"current_password": body["temporary_password"], "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 200 and changed.json()["must_change_password"] is False
    assert teacher.get(f"{API}/workspaces").status_code == 200
    assert teacher.post(f"{API}/auth/logout").status_code == 204
    assert login(teacher, "tess@example.com", body["temporary_password"]).status_code == 401
    assert login(teacher, "tess@example.com", NEW_PASSWORD).status_code == 200

    users = {u["email"]: u for u in admin.get(f"{API}/admin/users").json()}
    assert users["tess@example.com"]["last_login_at"] is not None
    assert users[ADMIN_EMAIL]["last_login_at"] is not None


def test_admin_user_list_filters(admin, app):
    teacher, _ = make_teacher(admin, app, "alice@example.com")
    make_student(teacher, app, "bob@example.com")
    roles = [u["role"] for u in admin.get(f"{API}/admin/users").json()]
    assert sorted(roles) == ["admin", "student", "teacher"]
    students = admin.get(f"{API}/admin/users", params={"role": "student"}).json()
    assert [u["email"] for u in students] == ["bob@example.com"]
    assert students[0]["created_by_name"] == "Tess Teacher"
    assert students[0]["enrollment_count"] == 0
    found = admin.get(f"{API}/admin/users", params={"q": "ALICE"}).json()
    assert [u["email"] for u in found] == ["alice@example.com"]
    assert found[0]["student_count"] == 1 and found[0]["student_limit"] == 4
    assert found[0]["uses_default_limit"] is True
    assert admin.get(f"{API}/admin/users", params={"q": "%"}).json() == []
    assert admin.get(f"{API}/admin/users", params={"role": "boss"}).status_code == 422


# --- Student limit -------------------------------------------------------------------


def test_student_limit_enforced_raised_and_lowered(admin, app):
    teacher, teacher_id = make_teacher(admin, app)
    for i in range(4):
        result = add_student(teacher, f"s{i}@example.com")
        assert result.status_code == 201, result.text
        assert result.json()["used"] == i + 1 and result.json()["limit"] == 4
    fifth = add_student(teacher, "s4@example.com")
    assert fifth.status_code == 409
    assert fifth.json()["detail"] == ("Student limit reached (4 of 4). Ask the admin to raise it.")
    assert teacher.get(f"{API}/teacher/students").json()["used"] == 4
    duplicate = add_student(teacher, ADMIN_EMAIL)  # Emails are unique across all users.
    assert duplicate.status_code == 409

    raised = admin.patch(f"{API}/admin/teachers/{teacher_id}", json={"student_limit": 5})
    assert raised.status_code == 200 and raised.json()["student_limit"] == 5
    assert add_student(teacher, "s4@example.com").status_code == 201
    assert teacher.get(f"{API}/teacher/students").json()["limit"] == 5

    lowered = admin.patch(f"{API}/admin/teachers/{teacher_id}", json={"student_limit": 2})
    assert lowered.status_code == 200 and lowered.json()["student_count"] == 5
    listing = teacher.get(f"{API}/teacher/students").json()
    assert listing["used"] == 5 and listing["limit"] == 2 and len(listing["students"]) == 5
    blocked = add_student(teacher, "s5@example.com")
    assert blocked.status_code == 409 and "(5 of 2)" in blocked.json()["detail"]

    for bad in [{"student_limit": -1}, {"student_limit": 1.5}, {"student_limit": "3"}, {}]:
        assert admin.patch(f"{API}/admin/teachers/{teacher_id}", json=bad).status_code == 422
    reset_default = admin.patch(f"{API}/admin/teachers/{teacher_id}", json={"student_limit": None})
    assert reset_default.json()["student_limit"] == 4
    assert reset_default.json()["uses_default_limit"] is True
    assert admin.patch(f"{API}/admin/teachers/{NIL}", json={"student_limit": 3}).status_code == 404


# --- Ownership between teachers ------------------------------------------------------


def test_teacher_cannot_touch_other_teachers_students_or_courses(admin, app):
    alice, _ = make_teacher(admin, app, "alice@example.com")
    bob, _ = make_teacher(admin, app, "bob@example.com")
    _, alice_student = make_student(alice, app, "as@example.com")
    _, bob_student = make_student(bob, app, "bs@example.com")
    alice_course = make_course(alice)
    bob_course = make_course(bob)

    emails = [s["email"] for s in bob.get(f"{API}/teacher/students").json()["students"]]
    assert emails == ["bs@example.com"]
    assert bob.delete(f"{API}/teacher/students/{alice_student}").status_code == 404
    enroll = f"{API}/workspaces/{{}}/enrollments/{{}}"
    assert bob.put(enroll.format(bob_course, alice_student)).status_code == 404
    assert bob.put(enroll.format(alice_course, bob_student)).status_code == 404
    assert bob.put(enroll.format(alice_course, alice_student)).status_code == 404
    assert bob.delete(enroll.format(alice_course, alice_student)).status_code == 404
    assert bob.get(f"{API}/workspaces/{alice_course}/enrollments").status_code == 404
    assert bob.get(f"{API}/workspaces/{alice_course}").status_code == 404
    # Students (not teachers) and teachers cannot be enrolled as students.
    assert alice.put(enroll.format(alice_course, NIL)).status_code == 404
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Enrollment)) == 0
    assert alice.get(f"{API}/teacher/students").json()["used"] == 1


# --- Students ------------------------------------------------------------------------


def test_student_sees_published_courses_of_their_teacher(admin, app):
    """Students see their own teacher's *published* courses; enrollment marks them assigned."""
    teacher, _ = make_teacher(admin, app)
    student, student_id = make_student(teacher, app)
    course = make_course(teacher, "Ecosystems")
    make_course(teacher, "Private planning")  # never published
    base = f"{API}/workspaces/{course}"
    assert student.get(f"{API}/student/courses").json() == []

    path = f"{base}/enrollments/{student_id}"
    assert teacher.put(path).status_code == 204
    assert teacher.put(path).status_code == 204  # Idempotent.
    enrolled = teacher.get(f"{base}/enrollments").json()
    assert [e["student_id"] for e in enrolled] == [student_id]
    assert student.get(f"{API}/student/courses").json() == []  # enrolled but unpublished

    extracted_source(app, base, teacher)
    approved(teacher, app, base)
    wait(app, teacher.post(base + "/notes/generate", json={}))
    assert teacher.post(base + "/publish").status_code == 200
    courses = student.get(f"{API}/student/courses").json()
    assert [(c["title"], c["subject"], c["teacher_name"], c["assigned"]) for c in courses] == [
        ("Ecosystems", "Biology", "Tess Teacher", True)
    ]
    assert courses[0]["units_total"] == 3 and courses[0]["units_done"] == 0
    for path_ in ["/workspaces", f"/workspaces/{course}", "/admin/users", "/teacher/students"]:
        assert student.get(API + path_).status_code == 403
    assert student.post(f"{API}/workspaces", json={"title": "Mine"}).status_code == 403

    assert teacher.delete(path).status_code == 204
    assert student.get(f"{API}/student/courses").json()[0]["assigned"] is False
    assert teacher.post(base + "/unpublish").status_code == 200
    assert student.get(f"{API}/student/courses").json() == []
    # Another teacher's published course is never visible.
    other, _ = make_teacher(admin, app, "other@example.com")
    other_base = f"{API}/workspaces/{make_course(other, 'Other')}"
    extracted_source(app, other_base, other)
    approved(other, app, other_base)
    wait(app, other.post(other_base + "/notes/generate", json={}))
    assert other.post(other_base + "/publish").status_code == 200
    assert student.get(f"{API}/student/courses").json() == []


# --- Deletion ------------------------------------------------------------------------


def test_admin_deletes_teacher_with_courses_files_and_students(admin, app):
    teacher, teacher_id = make_teacher(admin, app)
    student, student_id = make_student(teacher, app)
    course = make_course(teacher)
    assert upload(teacher, f"{API}/workspaces/{course}").status_code == 201
    assert upload(teacher, f"{API}/workspaces/{course}", "b.md", b"# B").status_code == 201
    teacher.put(f"{API}/workspaces/{course}/enrollments/{student_id}")
    keeper, _ = make_teacher(admin, app, "keeper@example.com")
    make_student(keeper, app, "kept@example.com")
    assert len(list(app.state.storage.root.iterdir())) == 2

    row = next(u for u in admin.get(f"{API}/admin/users").json() if u["id"] == teacher_id)
    assert (row["course_count"], row["file_count"], row["student_count"]) == (1, 2, 1)
    assert admin.delete(f"{API}/admin/users/{teacher_id}").status_code == 204

    assert list(app.state.storage.root.iterdir()) == []
    assert teacher.get(f"{API}/auth/me").status_code == 401
    assert student.get(f"{API}/auth/me").status_code == 401
    with app.state.session_factory() as db:
        assert db.get(User, UUID(student_id)) is None
        assert db.scalars(select(Workspace)).all() == []
        assert db.scalars(select(SourceDocument)).all() == []
        assert db.scalars(select(Enrollment)).all() == []
        emails = set(db.scalars(select(User.email)))
        assert emails == {ADMIN_EMAIL, "keeper@example.com", "kept@example.com"}
    assert admin.delete(f"{API}/admin/users/{teacher_id}").status_code == 404


def test_admin_cannot_delete_self_or_another_admin(admin, app):
    with app.state.session_factory() as db:
        me = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        other = User(
            email="admin2@example.com",
            display_name="Second admin",
            password_hash=password_hasher.hash("whatever-password"),
            role="admin",
        )
        db.add(other)
        db.commit()
        ids = (me.id, other.id)
    for user_id in ids:
        assert admin.delete(f"{API}/admin/users/{user_id}").status_code == 403
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 2


def test_deleting_student_removes_account_and_enrollments(admin, app):
    teacher, _ = make_teacher(admin, app)
    first, first_id = make_student(teacher, app, "first@example.com")
    _, second_id = make_student(teacher, app, "second@example.com")
    course = make_course(teacher)
    for sid in (first_id, second_id):
        teacher.put(f"{API}/workspaces/{course}/enrollments/{sid}")

    assert teacher.delete(f"{API}/teacher/students/{first_id}").status_code == 204
    assert first.get(f"{API}/auth/me").status_code == 401
    assert admin.delete(f"{API}/admin/users/{second_id}").status_code == 204
    with app.state.session_factory() as db:
        assert db.scalars(select(Enrollment)).all() == []
        assert db.scalar(select(func.count()).select_from(User).where(User.role == "student")) == 0
    assert teacher.get(f"{API}/workspaces/{course}").status_code == 200
    assert teacher.get(f"{API}/teacher/students").json()["used"] == 0


# --- Login lockout -------------------------------------------------------------------


def test_login_lockout_by_email(admin, app):
    c = new_client(app)
    for _ in range(4):
        assert login(c, ADMIN_EMAIL, "wrong-password").status_code == 401
    fifth = login(c, " ADMIN@example.com", "wrong-password")
    assert fifth.status_code == 429
    assert "Too many failed login attempts" in fifth.json()["detail"]
    assert login(c, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 429
    # Keyed by email, not by client address: other accounts are unaffected.
    teacher, _ = make_teacher(admin, app)
    assert teacher.get(f"{API}/auth/me").status_code == 200


def test_successful_login_resets_failure_count(client):
    for _ in range(4):
        assert login(client, ADMIN_EMAIL, "wrong-password").status_code == 401
    assert login(client, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    for _ in range(4):
        assert login(client, ADMIN_EMAIL, "wrong-password").status_code == 401


# --- Migration -----------------------------------------------------------------------


def test_migration_upgrades_existing_users_and_downgrades(tmp_path):
    from app.db.session import build_engine

    config = migrate(tmp_path, "fd3aeee870c4")
    engine = build_engine(config.attributes["database_url"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, email, display_name, password_hash, created_at, "
                "updated_at) VALUES (:id, 'legacy@example.com', 'Legacy', 'hash', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": "1" * 32},
        )
        connection.execute(
            text(
                "INSERT INTO sessions VALUES "
                "(:id, :user, :token, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": "2" * 32, "user": "1" * 32, "token": "t" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO workspaces VALUES (:id, :owner, 'Lesson', NULL, NULL, "
                "'introductory', 40, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": "3" * 32, "owner": "1" * 32},
        )

    def counts():
        with engine.connect() as connection:
            return [
                connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()
                for table in ("users", "sessions", "workspaces")
            ]

    command.upgrade(config, "head")
    # The batch rebuild of users must not cascade-delete sessions or workspaces.
    assert counts() == [1, 1, 1]
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT role, must_change_password, student_limit, last_login_at FROM users")
        ).one()
        assert tuple(row) == ("teacher", 0, None, None)
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
    command.check(config)

    command.downgrade(config, "fd3aeee870c4")
    assert counts() == [1, 1, 1]
    with engine.connect() as connection:
        columns = {r[1] for r in connection.execute(text("PRAGMA table_info(users)"))}
        assert "role" not in columns
        tables = {r[0] for r in connection.execute(text("SELECT name FROM sqlite_master"))}
        assert "enrollments" not in tables
    command.upgrade(config, "head")
    assert counts() == [1, 1, 1]
    engine.dispose()
