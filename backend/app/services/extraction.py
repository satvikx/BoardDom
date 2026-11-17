import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore

from sqlalchemy import update

from app.models.entities import SourceDocument, SourceUnit, utcnow


def failure(code, message):
    return dict(status="failed", units=[], warnings=[], code=code, message=message)


class ExtractionWorker:
    """One admitted job, no unbounded queue; the parser child has a hard timeout."""

    def __init__(self, factory, storage, settings):
        self.factory, self.storage, self.settings = factory, storage, settings
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="extract")
        self.capacity = BoundedSemaphore(1)

    def recover(self):
        with self.factory() as db:
            db.execute(
                update(SourceDocument)
                .where(SourceDocument.extraction_status == "processing")
                .values(
                    extraction_status="failed",
                    extraction_error_code="interrupted",
                    extraction_error_message="Server restarted during extraction. Retry extraction.",
                    extraction_finished_at=utcnow(),
                    extraction_attempt_id=None,
                )
            )
            db.commit()

    def close(self):
        self.pool.shutdown(wait=True)

    def parse(self, key, media_type):
        with tempfile.TemporaryDirectory(prefix="boardom-extract-") as directory:
            output = Path(directory) / "result.json"
            try:
                subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).with_name("parser.py")),
                        str(self.storage.path(key)),
                        media_type,
                        str(self.settings.max_pdf_pages),
                        str(self.settings.max_extracted_characters),
                        str(output),
                    ],
                    timeout=self.settings.extraction_timeout_seconds,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return json.loads(output.read_text(encoding="utf-8"))
            except subprocess.TimeoutExpired:
                return failure(
                    "timeout",
                    "Extraction timed out. Split the source into smaller files and retry.",
                )
            except Exception:
                return failure(
                    "parser_failed",
                    "Extraction could not complete. Check the source file and retry.",
                )

    def finish(self, document_id, attempt, result):
        with self.factory() as db:
            claimed = db.execute(
                update(SourceDocument)
                .where(
                    SourceDocument.id == document_id,
                    SourceDocument.extraction_status == "processing",
                    SourceDocument.extraction_attempt_id == attempt,
                )
                .values(
                    extraction_status=result["status"],
                    extraction_error_code=result["code"],
                    extraction_error_message=result["message"],
                    extraction_warnings=result["warnings"],
                    extraction_finished_at=utcnow(),
                    extracted_at=utcnow() if result["status"] == "extracted" else None,
                    content_revision=SourceDocument.content_revision + 1,
                )
            )
            if not claimed.rowcount:
                return
            # Failed/needs-OCR attempts may be retried; remove their old empty units.
            from sqlalchemy import delete

            db.execute(delete(SourceUnit).where(SourceUnit.document_id == document_id))
            db.add_all(SourceUnit(document_id=document_id, **unit) for unit in result["units"])
            db.commit()

    def run(self, document_id, attempt, key, media_type):
        try:
            self.finish(document_id, attempt, self.parse(key, media_type))
        finally:
            self.capacity.release()
