"""Part 7: the offline demo seed creates a complete, published course; reruns are safe."""

from alembic.config import Config
from sqlalchemy import func, select

from alembic import command
from app.core.config import BACKEND_ROOT
from app.db.session import build_engine, session_factory
from app.models.entities import Artifact, Concept, User, Video, Workspace


def test_seed_demo_builds_and_rebuilds(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'seed.db'}"
    for name, value in {
        "BOARDOM_DATABASE_URL": url,
        "BOARDOM_UPLOAD_DIR": str(tmp_path / "uploads"),
        "BOARDOM_CHROMA_DIR": str(tmp_path / "chroma"),
        "BOARDOM_OPENAI_API_KEY": "",
        "BOARDOM_ENVIRONMENT": "test",
    }.items():
        monkeypatch.setenv(name, value)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    from app.seed_demo import seed

    assert seed() == 0
    assert seed() == 0 and "already seeded" in capsys.readouterr().out
    assert seed(reset=True) == 0
    engine = build_engine(url)
    with session_factory(engine)() as db:

        def count(model, *where):
            return db.scalar(select(func.count()).select_from(model).where(*where))

        assert count(User, User.role == "teacher") == 1 and count(User, User.role == "student") == 3
        workspace = db.scalar(select(Workspace))
        assert count(Workspace) == 1 and workspace.published_at and workspace.has_lab
        kinds = set(db.scalars(select(Artifact.kind)))
        assert kinds == {"unit_notes", "lab_manual", "lesson_plan", "rubric"}
        assert count(Concept) >= 3
        video = db.scalar(select(Video))
        assert count(Video) == 1 and video.status == "ready"
    videos = list((tmp_path / "uploads" / "videos").iterdir())
    assert len(videos) == 1  # the reset removed the first run's video file
    engine.dispose()
