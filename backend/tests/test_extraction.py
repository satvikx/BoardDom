import io
import subprocess
from unittest.mock import patch
from uuid import UUID

import pytest
from conftest import ORIGIN, register, upload, workspace
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select

from app.models.entities import SourceDocument, SourceUnit
from app.services.parser import run


def pdf(texts, encrypted=False):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {NameObject("/F1"): writer._add_object(font)}
                    )
                }
            )
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    "name,data,expected",
    [
        ("text.txt", b"hello\r\n  world\x00", "hello\n  world"),
        ("bom.txt", b"\xef\xbb\xbfhello", "hello"),
        (
            "notes.md",
            b"# Heading\n```\n# not a heading\n```\n",
            "# Heading\n```\n# not a heading\n```\n",
        ),
    ],
)
def test_text_parser(tmp_path, name, data, expected):
    path = tmp_path / name
    path.write_bytes(data)
    result = run(path, "text/plain", 200, 500000)
    assert result["status"] == "extracted"
    assert result["units"][0]["original_text"] == expected
    assert result["units"][0]["page_number"] is None
    assert result["units"][0]["label"] == "Document"


@pytest.mark.parametrize(
    "texts,status",
    [
        (["First", "Second"], "extracted"),
        (["", ""], "needs_ocr"),
        (["First", "", "Third"], "extracted"),
    ],
)
def test_pdf_pages(tmp_path, texts, status):
    path = tmp_path / "test.pdf"
    path.write_bytes(pdf(texts))
    result = run(path, "application/pdf", 200, 500000)
    assert result["status"] == status
    assert [u["page_number"] for u in result["units"]] == list(range(1, len(texts) + 1))
    assert [u["original_text"].strip() for u in result["units"]] == texts
    if status == "extracted" and "" in texts:
        assert "2" in result["warnings"][0] and "blank or image-based" in result["warnings"][0]


@pytest.mark.parametrize(
    "data,media,pages,chars,code",
    [
        (pdf(["A"], True), "application/pdf", 200, 500000, "encrypted_pdf"),
        (b"%PDF-broken", "application/pdf", 200, 500000, "invalid_source"),
        (pdf(["A", "B"]), "application/pdf", 1, 500000, "page_limit"),
        (b"long text", "text/plain", 200, 2, "character_limit"),
        (b" \n ", "text/plain", 200, 500000, "empty_content"),
    ],
)
def test_parser_failures(tmp_path, data, media, pages, chars, code):
    path = tmp_path / "input"
    path.write_bytes(data)
    result = run(path, media, pages, chars)
    assert result["status"] == "failed" and result["code"] == code
    assert result["units"] == []


@pytest.fixture
def source(signed_in, app):
    base = workspace(signed_in)
    doc = upload(signed_in, base).json()
    url = f"{base}/documents/{doc['id']}"
    with patch.object(app.state.worker.pool, "submit") as schedule:
        response = signed_in.post(url + "/extract")
        assert response.status_code == 202
        assert signed_in.post(url + "/extract").status_code == 409
        assert schedule.call_count == 1
    app.state.worker.run(
        UUID(doc["id"]),
        response.json()["extraction_attempt_id"],
        next(app.state.storage.root.iterdir()).name,
        "text/plain",
    )
    return url


def test_edit_review_export(signed_in, source):
    content = signed_in.get(source + "/content").json()
    unit = content["units"][0]
    path = source + "/units/" + unit["id"]
    assert signed_in.post(source + "/extract").status_code == 409
    result = signed_in.patch(
        path, json={"corrected_text": "Teacher correction", "expected_revision": 0}
    )
    assert result.status_code == 200
    assert result.json()["original_text"] == "Lesson notes"
    assert result.json()["effective_text"] == "Teacher correction"
    assert (
        signed_in.patch(path, json={"corrected_text": "stale", "expected_revision": 0}).status_code
        == 409
    )
    assert (
        signed_in.patch(
            source + "/review", json={"reviewed": True, "expected_content_revision": 1}
        ).status_code
        == 409
    )
    reviewed = signed_in.patch(
        source + "/review", json={"reviewed": True, "expected_content_revision": 2}
    )
    assert reviewed.status_code == 200 and reviewed.json()["reviewed_at"]
    assert signed_in.get(source + "/content/download").content == b"Teacher correction"
    empty = signed_in.patch(path, json={"corrected_text": "", "expected_revision": 1}).json()
    assert empty["effective_text"] == ""
    assert signed_in.get(source + "/content").json()["document"]["reviewed_at"] is None
    assert (
        signed_in.patch(
            source + "/review", json={"reviewed": True, "expected_content_revision": 3}
        ).status_code
        == 422
    )
    reset = signed_in.patch(path, json={"corrected_text": None, "expected_revision": 2}).json()
    assert reset["effective_text"] == "Lesson notes" and reset["id"] == unit["id"]


def test_content_authorization_and_mismatch(signed_in, app, source):
    unit = signed_in.get(source + "/content").json()["units"][0]
    other = upload(signed_in, workspace(signed_in)).json()
    mismatch = (
        f"/api/v1/workspaces/{other['workspace_id']}/documents/{other['id']}/units/{unit['id']}"
    )
    assert (
        signed_in.patch(mismatch, json={"corrected_text": "X", "expected_revision": 0}).status_code
        == 404
    )
    with TestClient(app, headers={"Origin": ORIGIN}) as stranger:
        register(stranger, "stranger@example.com")
        for method, suffix, body in [
            ("GET", "/content", None),
            ("GET", "/content/download", None),
            ("POST", "/extract", None),
            ("PATCH", "/review", {"reviewed": True, "expected_content_revision": 1}),
            ("PATCH", "/units/" + unit["id"], {"corrected_text": "X", "expected_revision": 0}),
        ]:
            assert stranger.request(method, source + suffix, json=body).status_code == 404


def test_timeout_releases_capacity(signed_in, app):
    base = workspace(signed_in)
    doc = upload(signed_in, base).json()
    url = f"{base}/documents/{doc['id']}"
    with patch.object(app.state.worker.pool, "submit"):
        attempt = signed_in.post(url + "/extract").json()["extraction_attempt_id"]
    with patch(
        "app.services.extraction.subprocess.run",
        side_effect=subprocess.TimeoutExpired("parser", 0.01),
    ):
        app.state.worker.run(
            UUID(doc["id"]), attempt, next(app.state.storage.root.iterdir()).name, "text/plain"
        )
    content = signed_in.get(url + "/content").json()
    assert content["document"]["extraction_error_code"] == "timeout"
    assert app.state.worker.capacity.acquire(False)
    app.state.worker.capacity.release()


def test_interruption_stale_attempt_and_delete(signed_in, app):
    base = workspace(signed_in)
    doc = upload(signed_in, base).json()
    url = f"{base}/documents/{doc['id']}"
    worker = app.state.worker
    with patch.object(worker.pool, "submit"):
        first = signed_in.post(url + "/extract").json()["extraction_attempt_id"]
        worker.recover()
        worker.capacity.release()
        second = signed_in.post(url + "/extract").json()["extraction_attempt_id"]
    result = {
        "status": "extracted",
        "units": [dict(position=0, page_number=None, label="Document", original_text="Text")],
        "warnings": [],
        "code": None,
        "message": None,
    }
    worker.finish(UUID(doc["id"]), first, result)
    assert signed_in.get(url + "/content").json()["document"]["extraction_status"] == "processing"
    assert signed_in.delete(url).status_code == 204
    worker.finish(UUID(doc["id"]), second, result)
    worker.capacity.release()
    with app.state.session_factory() as db:
        assert db.get(SourceDocument, UUID(doc["id"])) is None
        assert db.scalars(select(SourceUnit)).all() == []


def test_migration_preserves_layer_one(tmp_path):
    from alembic.config import Config
    from sqlalchemy import text

    from alembic import command
    from app.core.config import BACKEND_ROOT
    from app.db.session import build_engine

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    config.attributes["database_url"] = url
    command.upgrade(config, "a8d4aebbd5ea")
    engine = build_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users VALUES (:id,'legacy@example.com','Legacy','hash',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": "1" * 32},
        )
        connection.execute(
            text(
                "INSERT INTO workspaces VALUES (:id,:owner,'Lesson',NULL,NULL,'introductory',40,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": "2" * 32, "owner": "1" * 32},
        )
        connection.execute(
            text(
                "INSERT INTO source_documents VALUES (:id,:workspace,'notes.txt',:key,'text/plain',3,'uploaded',CURRENT_TIMESTAMP)"
            ),
            {"id": "3" * 32, "workspace": "2" * 32, "key": "4" * 32},
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT original_filename,storage_key,extraction_status,content_revision FROM source_documents"
            )
        ).one()
        assert tuple(row) == ("notes.txt", "4" * 32, "uploaded", 0)
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 1
    command.check(config)
    engine.dispose()
