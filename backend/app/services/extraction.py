import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore

from sqlalchemy import update

from app.ai import AIError
from app.models.entities import SourceDocument, SourceUnit, utcnow


def failure(code, message):
    return dict(status="failed", units=[], warnings=[], code=code, message=message)


class ExtractionWorker:
    """One admitted job, no unbounded queue; the parser child has a hard timeout."""

    def __init__(self, factory, storage, settings, provider=None):
        self.factory, self.storage, self.settings = factory, storage, settings
        self.provider = provider  # reads text from images (scans, photos)
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

    def parse(self, key, media_type, workdir=None):
        if workdir is None:
            with tempfile.TemporaryDirectory(prefix="boardom-extract-") as directory:
                return self.parse(key, media_type, Path(directory))
        output = workdir / "result.json"
        images = workdir / "images"
        images.mkdir(exist_ok=True)
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
                    str(images),
                    str(self.settings.max_ocr_pages),
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

    def recognize(self, result, images: Path):
        """Send page images (scans, photos) to the AI provider's text recognition."""
        pages = result.get("ocr") or []
        if not pages or result["status"] == "failed":
            return result
        if self.provider is None or not hasattr(self.provider, "read_image"):
            return result
        texts = {}
        try:
            for item in pages:
                data = (images / item["file"]).read_bytes()
                texts[item["page"]] = self.provider.read_image(data, "image/png").strip()
        except AIError as exc:
            if result["status"] == "needs_ocr":
                result["message"] = f"{result['message']} {exc.message}"
                result["code"] = exc.code
            else:
                result["warnings"].append(f"Scanned pages were not read: {exc.message}")
            return result
        if None in texts:  # a single image
            result["units"] = [
                dict(position=0, page_number=None, label="Image", original_text=texts[None])
            ]
        else:
            for unit in result["units"]:
                if unit["page_number"] in texts:
                    unit["original_text"] = texts[unit["page_number"]]
        total = sum(len(u["original_text"]) for u in result["units"])
        if total > self.settings.max_extracted_characters:
            return failure(
                "character_limit",
                "Character limit exceeded. Split the source and upload smaller files.",
            )
        if any(u["original_text"].strip() for u in result["units"]):
            result.update(status="extracted", code=None, message=None)
            result["warnings"].append(
                f"Text on {len(texts)} image(s) was read by the AI. "
                "Check it against the original before relying on it."
            )
        else:
            result.update(
                status="needs_ocr",
                code="no_text_found",
                message="No readable text was found in the image(s).",
            )
        return result

    def run(self, document_id, attempt, key, media_type):
        try:
            with tempfile.TemporaryDirectory(prefix="boardom-extract-") as directory:
                workdir = Path(directory)
                result = self.parse(key, media_type, workdir)
                result = self.recognize(result, workdir / "images")
            self.finish(document_id, attempt, result)
        finally:
            self.capacity.release()
