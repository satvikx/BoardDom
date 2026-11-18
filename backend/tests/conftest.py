from uuid import UUID

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient

from alembic import command
from app.core.config import BACKEND_ROOT, Settings
from app.main import create_app
from app.models.entities import Job, SourceDocument, SourceUnit

ORIGIN = "http://localhost:3000"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "BoardomAdmin#2026"
ADMIN_PIN = "482916"


def make_settings(tmp_path, **overrides):
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        max_upload_bytes=128,
        frontend_origin=ORIGIN,
        environment="test",
        allow_public_signup=True,
        admin_email=ADMIN_EMAIL,
        admin_password=ADMIN_PASSWORD,
        admin_reset_pin=ADMIN_PIN,
        default_student_limit=4,
        # Offline: never pick up a real key or gateway from the shell environment.
        openai_api_key=None,
        openai_base_url=None,
        **overrides,
    )


@pytest.fixture
def app(tmp_path):
    settings = make_settings(tmp_path)
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


PHOTOSYNTHESIS = [
    "# Photosynthesis\n\nPlants turn light energy into chemical energy. Chlorophyll absorbs "
    "light in the leaves. Example: a leaf in sunlight produces glucose and oxygen.",
    "# Respiration\n\nCells release energy from glucose. Respiration happens in the "
    "mitochondria. Example: muscles use respiration during exercise.",
    "# Food chains\n\nEnergy flows from producers to consumers. Each step loses energy as heat. "
    "Example: grass, rabbit, fox.",
]


def extracted_source(app, base, client, texts=PHOTOSYNTHESIS, name="notes.md"):
    """Upload a small file, then mark it extracted with the given page texts."""
    doc = upload(client, base, name, b"# Notes").json()
    with app.state.session_factory() as db:
        row = db.get(SourceDocument, UUID(doc["id"]))
        row.extraction_status = "extracted"
        row.content_revision = 1
        for position, text in enumerate(texts):
            db.add(
                SourceUnit(
                    document_id=row.id,
                    position=position,
                    page_number=position + 1,
                    label=f"Page {position + 1}",
                    original_text=text,
                )
            )
        db.commit()
    return doc["id"]


def wait(app, response, expect="succeeded"):
    assert response.status_code == 202, response.text
    job = response.json()
    app.state.jobs.wait(UUID(job["id"]))
    with app.state.session_factory() as db:
        row = db.get(Job, UUID(job["id"]))
        assert row.status == expect, row.message
        return row


@pytest.fixture
def course(signed_in, app):
    base = workspace(signed_in)
    extracted_source(app, base, signed_in)
    return base


def approved(client, app, base):
    wait(app, client.post(base + "/syllabus/generate"))
    syllabus = client.get(base + "/syllabus").json()
    result = client.post(
        base + "/syllabus/approve", json={"expected_revision": syllabus["revision"]}
    )
    assert result.status_code == 200, result.text
    return result.json()
