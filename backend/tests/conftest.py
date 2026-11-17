import pytest
from alembic.config import Config
from fastapi.testclient import TestClient

from alembic import command
from app.core.config import BACKEND_ROOT, Settings
from app.main import create_app

ORIGIN = "http://localhost:3000"


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=128,
        frontend_origin=ORIGIN,
        environment="test",
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = settings.resolved_database_url
    command.upgrade(config, "head")
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        yield client


def register(client, email="teacher@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Alex Teacher", "password": "lesson-password"},
    )


@pytest.fixture
def signed_in(client):
    assert register(client).status_code == 201
    return client


def workspace(client):
    response = client.post("/api/v1/workspaces", json={"title": "Ecosystems"})
    assert response.status_code == 201, response.text
    return f"/api/v1/workspaces/{response.json()['id']}"


def upload(client, base, name="notes.txt", content=b"Lesson notes"):
    return client.post(base + "/documents", files={"file": (name, content, "image/jpeg")})
