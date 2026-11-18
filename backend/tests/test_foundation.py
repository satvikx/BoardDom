from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import ORIGIN, register, upload, workspace
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.security import COOKIE_NAME, token_digest
from app.models.entities import SessionToken, SourceDocument, User, utcnow


def test_authentication_and_session_storage(client, app):
    result = register(client, "  TEACHER@Example.com ")
    assert result.status_code == 201
    assert result.json()["email"] == "teacher@example.com"
    assert "hash" not in result.text
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Max-Age=" in cookie and "expires=" in cookie
    token = client.cookies[COOKIE_NAME]
    with app.state.session_factory() as db:
        stored = db.scalar(select(SessionToken))
        assert stored.token_hash == token_digest(token) and stored.token_hash != token
        assert db.scalar(select(User)).password_hash.startswith("$argon2id$")
        assert stored.expires_at > utcnow()
    assert client.get("/api/v1/auth/me").json()["display_name"] == "Alex Teacher"
    assert register(client, "TEACHER@example.com").status_code == 409
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.clear()
    bad = client.post(
        "/api/v1/auth/login", json={"email": "teacher@example.com", "password": "incorrect"}
    )
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "unknown@example.com", "password": "incorrect"}
    )
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json() == {"detail": "Invalid email or password."}
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "TEACHER@example.com", "password": "lesson-password"},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me").status_code == 200


def test_session_expiry_and_rotation(signed_in, app):
    token = signed_in.cookies[COOKIE_NAME]
    signed_in.post(
        "/api/v1/auth/login", json={"email": "teacher@example.com", "password": "lesson-password"}
    )
    with app.state.session_factory() as db:
        assert (
            db.scalar(select(SessionToken).where(SessionToken.token_hash == token_digest(token)))
            is None
        )
        session = db.scalar(select(SessionToken))
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert signed_in.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "data",
    [
        {"email": "not-an-email"},
        {"password": "short"},
        {"password": "x" * 129},
        {"display_name": "   "},
    ],
)
def test_invalid_registration(client, data):
    body = {"email": "test@example.com", "password": "long-password", "display_name": "Name"} | data
    result = client.post("/api/v1/auth/register", json=body)
    assert result.status_code == 422
    assert body["password"] not in result.text


def test_unauthenticated_access(client):
    base = "/api/v1/workspaces/00000000-0000-0000-0000-000000000001"
    for method, path in [
        ("GET", "/api/v1/workspaces"),
        ("GET", base),
        ("PATCH", base),
        ("DELETE", base),
        ("GET", base + "/documents"),
    ]:
        assert client.request(method, path, json={"title": "A"}).status_code == 401
    assert upload(client, base).status_code == 401
    assert client.post("/api/v1/workspaces", json={"title": "A"}).status_code == 401


def test_workspace_crud_and_validation(signed_in):
    base = workspace(signed_in)
    data = signed_in.get(base).json()
    assert data["lesson_duration_minutes"] == 40
    assert data["created_at"].endswith("Z")
    assert len(signed_in.get("/api/v1/workspaces").json()) == 1
    assert (
        signed_in.patch(base, json={"description": "Notes", "subject": "Biology"}).status_code
        == 200
    )
    updated = signed_in.patch(base, json={"title": "New title", "description": None}).json()
    assert updated["description"] is None and updated["subject"] == "Biology"
    for data in [
        {"title": " "},
        {"title": None},
        {"learner_level": "expert"},
        {"learner_level": None},
        {"lesson_duration_minutes": 0},
        {"lesson_duration_minutes": 1.5},
        {"lesson_duration_minutes": None},
        {"description": "x" * 5001},
        {"subject": "x" * 101},
    ]:
        assert signed_in.patch(base, json=data).status_code == 422
    assert signed_in.delete(base).status_code == 204
    assert signed_in.get(base).status_code == 404


def test_updated_sort_order(signed_in):
    first = workspace(signed_in)
    second = workspace(signed_in)
    assert signed_in.get("/api/v1/workspaces").json()[0]["id"] == second.rsplit("/", 1)[1]
    signed_in.patch(first, json={"title": "Updated"})
    assert signed_in.get("/api/v1/workspaces").json()[0]["id"] == first.rsplit("/", 1)[1]


def test_ownership(signed_in, app):
    base = workspace(signed_in)
    doc = upload(signed_in, base).json()
    path = f"{base}/documents/{doc['id']}"
    with TestClient(app, headers={"Origin": ORIGIN}) as other:
        assert register(other, "other@example.com").status_code == 201
        assert other.get("/api/v1/workspaces").json() == []
        for method, url in [
            ("GET", base),
            ("PATCH", base),
            ("DELETE", base),
            ("GET", base + "/documents"),
            ("GET", path + "/download"),
            ("DELETE", path),
        ]:
            assert other.request(method, url, json={"title": "Stolen"}).status_code == 404
        assert upload(other, base).status_code == 404
    other_workspace = workspace(signed_in)
    assert signed_in.get(f"{other_workspace}/documents/{doc['id']}/download").status_code == 404


@pytest.mark.parametrize(
    ("name", "content", "media"),
    [
        ("notes.txt", b"Hello, class!", "text/plain"),
        ("notes.md", "# Ecosystèmes 🌱".encode(), "text/markdown"),
        ("source.PDF", b"%PDF-1.4\n%%EOF", "application/pdf"),
        ("../../notes.txt", b"safe path", "text/plain"),
    ],
)
def test_upload_download_and_document_delete(signed_in, app, name, content, media):
    base = workspace(signed_in)
    result = upload(signed_in, base, name, content)
    assert result.status_code == 201, result.text
    doc = result.json()
    assert doc["original_filename"] == name and doc["status"] == "uploaded"
    assert doc["media_type"] == media and doc["size_bytes"] == len(content)
    assert "storage_key" not in doc
    assert signed_in.get(base + "/documents").json()[0] == doc
    path = f"{base}/documents/{doc['id']}"
    response = signed_in.get(path + "/download")
    assert response.content == content
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "../" not in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    files = list(app.state.storage.root.iterdir())
    assert len(files) == 1 and len(files[0].name) == 32
    assert signed_in.delete(path).status_code == 204
    assert list(app.state.storage.root.iterdir()) == []
    assert signed_in.get(path + "/download").status_code == 404


@pytest.mark.parametrize(
    ("name", "content", "status"),
    [
        ("bad.exe", b"abc", 415),
        ("empty.txt", b"", 422),
        ("huge.txt", b"x" * 129, 413),
        ("fake.pdf", b"not pdf", 422),
        ("bad.md", b"\xff\xfe", 422),
        ("bad.txt", b"abc\xc3", 422),
    ],
)
def test_rejected_uploads(signed_in, app, name, content, status):
    base = workspace(signed_in)
    assert upload(signed_in, base, name, content).status_code == status
    assert signed_in.get(base + "/documents").json() == []
    assert not app.state.storage.root.exists() or list(app.state.storage.root.iterdir()) == []


def test_workspace_delete_cleans_files_and_foreign_keys(signed_in, app):
    base = workspace(signed_in)
    upload(signed_in, base)
    upload(signed_in, base, "notes.md", b"# Notes")
    assert len(list(app.state.storage.root.iterdir())) == 2
    assert signed_in.delete(base).status_code == 204
    assert list(app.state.storage.root.iterdir()) == []
    with app.state.session_factory() as db:
        assert db.scalar(text("PRAGMA foreign_keys")) == 1
        assert db.scalars(select(SourceDocument)).all() == []


@pytest.mark.parametrize(
    "origin", ["https://untrusted.example", "null", "http://localhost:3000.evil.test", ""]
)
def test_csrf_rejects_untrusted_and_missing_origins(client, origin):
    for path in ["auth/register", "auth/login", "auth/logout", "workspaces"]:
        assert (
            client.post(f"/api/v1/{path}", headers={"Origin": origin}, json={}).status_code == 403
        )
    assert (
        client.patch("/api/v1/workspaces/nope", headers={"Origin": origin}, json={}).status_code
        == 403
    )
    assert client.delete("/api/v1/workspaces/nope", headers={"Origin": origin}).status_code == 403
    client.headers.pop("origin")
    assert client.post("/api/v1/auth/logout").status_code == 403


def test_missing_file_is_explicit_and_preserves_metadata(signed_in, app):
    base = workspace(signed_in)
    doc = upload(signed_in, base).json()
    next(app.state.storage.root.iterdir()).unlink()
    assert signed_in.get(f"{base}/documents/{doc['id']}/download").status_code == 409
    assert signed_in.delete(base).status_code == 409
    assert signed_in.get(base).status_code == 200
    assert len(signed_in.get(base + "/documents").json()) == 1


def test_failed_upload_db_insert_cleans_file(signed_in, app):
    base = workspace(signed_in)
    with patch("sqlalchemy.orm.Session.commit", side_effect=SQLAlchemyError("private details")):
        response = upload(signed_in, base)
    assert response.status_code == 503 and "private details" not in response.text
    assert list(app.state.storage.root.iterdir()) == []
    assert signed_in.get(base + "/documents").json() == []


def test_failed_delete_db_commit_restores_files(signed_in, app):
    base = workspace(signed_in)
    doc = upload(signed_in, base).json()
    with patch("sqlalchemy.orm.Session.commit", side_effect=SQLAlchemyError()):
        assert signed_in.delete(base).status_code == 503
    assert signed_in.get(base).status_code == 200
    assert signed_in.get(f"{base}/documents/{doc['id']}/download").content == b"Lesson notes"
    assert all(not p.name.startswith(".") for p in app.state.storage.root.iterdir())


def test_storage_failure_is_explicit(signed_in, app):
    base = workspace(signed_in)
    with patch.object(Path, "open", side_effect=PermissionError()):
        assert upload(signed_in, base).status_code == 503
    doc = upload(signed_in, base).json()
    with patch.object(Path, "rename", side_effect=PermissionError()):
        assert signed_in.delete(base).status_code == 503
    assert signed_in.get(f"{base}/documents/{doc['id']}/download").status_code == 200


def test_settings_paths_are_launch_directory_independent(tmp_path, monkeypatch):
    from app.core.config import Settings

    settings = Settings(_env_file=None)
    before = (settings.resolved_database_url, settings.resolved_upload_dir)
    monkeypatch.chdir(tmp_path)
    assert before == (settings.resolved_database_url, settings.resolved_upload_dir)


def test_health_and_limit(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/config").json() == {
        "max_upload_bytes": 128,
        "allow_public_signup": True,
    }


def test_partial_delete_staging_restores_earlier_files(signed_in, app):
    base = workspace(signed_in)
    upload(signed_in, base, "one.txt", b"one")
    upload(signed_in, base, "two.txt", b"two")
    original_rename = Path.rename
    calls = 0

    def failing_second_rename(path, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("simulated failure")
        return original_rename(path, target)

    with patch.object(Path, "rename", failing_second_rename):
        assert signed_in.delete(base).status_code == 503
    assert sorted(p.read_bytes() for p in app.state.storage.root.iterdir()) == [b"one", b"two"]
    assert len(signed_in.get(base + "/documents").json()) == 2


def test_post_commit_cleanup_failure_is_not_success(signed_in, app):
    base = workspace(signed_in)
    upload(signed_in, base)
    with patch.object(Path, "unlink", side_effect=PermissionError()):
        response = signed_in.delete(base)
    assert response.status_code == 503
    assert "administrator attention" in response.json()["detail"]
    assert signed_in.get(base).status_code == 404
    assert next(app.state.storage.root.iterdir()).name.startswith(".delete-")


def test_secure_cookie_setting(client, app):
    app.state.settings.cookie_secure = True
    result = register(client)
    assert "Secure" in result.headers["set-cookie"]


def test_storage_key_rejects_traversal(app):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        app.state.storage.path("../../secret")
    assert error.value.status_code == 503
