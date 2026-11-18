import codecs
import logging
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models.entities import SourceDocument

logger = logging.getLogger(__name__)
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
TEXT_SUFFIXES = {".txt", ".md"}
SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}


class FileStorage:
    def __init__(self, root: Path, max_bytes: int):
        self.root = root
        self.max_bytes = max_bytes

    def path(self, key: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", key):
            raise HTTPException(503, "Invalid file storage reference.")
        path = self.root / key
        if path.is_symlink():
            raise HTTPException(503, "Stored file is unavailable.")
        return path

    def remove(self, key: str) -> None:
        try:
            self.path(key).unlink()
        except OSError as exc:
            raise HTTPException(503, "Could not remove stored file. Please retry.") from exc

    def save(self, upload: UploadFile) -> tuple[str, str, str, int]:
        filename = upload.filename or ""
        if (
            not filename
            or len(filename) > 255
            or any(ord(c) < 32 or ord(c) == 127 for c in filename)
        ):
            raise HTTPException(422, "Choose a file with a valid filename (up to 255 characters).")
        # Original name is metadata only, including any directory-like text.
        suffix = Path(filename).suffix.lower()
        if suffix not in MEDIA_TYPES:
            raise HTTPException(
                415,
                "Supported files: PDF, Markdown (.md), text (.txt), and images "
                "(.png, .jpg, .jpeg, .webp).",
            )
        key = uuid4().hex
        path = self.path(key)
        created = False
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            size = 0
            decoder = codecs.getincrementaldecoder("utf-8")() if suffix in TEXT_SUFFIXES else None
            prefix = b""  # first 12 bytes, for the file signature check
            with path.open("xb") as destination:
                created = True
                while chunk := upload.file.read(64 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise HTTPException(413, f"File exceeds the {self.max_bytes} byte limit.")
                    if len(prefix) < 12:
                        prefix = (prefix + chunk)[:12]
                    if decoder:
                        decoder.decode(chunk)
                    destination.write(chunk)
                if decoder:
                    decoder.decode(b"", final=True)
            if size == 0:
                raise HTTPException(422, "Empty files cannot be uploaded.")
            if suffix in SIGNATURES and not prefix.startswith(SIGNATURES[suffix]):
                kind = "PDF" if suffix == ".pdf" else "image"
                raise HTTPException(422, f"The file does not have a valid {kind} signature.")
            if suffix == ".webp" and not (prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"):
                raise HTTPException(422, "The file does not have a valid image signature.")
            return key, filename, MEDIA_TYPES[suffix], size
        except Exception as exc:
            if created:
                self.remove(key)
            if isinstance(exc, UnicodeDecodeError):
                raise HTTPException(
                    422, "Text and Markdown files must use UTF-8 encoding."
                ) from exc
            if isinstance(exc, OSError):
                raise HTTPException(503, "Could not save file. Please retry.") from exc
            raise
        finally:
            upload.file.close()

    def open_download(self, key: str):
        try:
            return self.path(key).open("rb")
        except FileNotFoundError as exc:
            raise HTTPException(
                409, "The stored file is missing. Contact the administrator."
            ) from exc
        except OSError as exc:
            raise HTTPException(503, "Could not read stored file. Please retry.") from exc

    def delete_records(
        self, db: Session, documents: Iterable[SourceDocument], delete_metadata: Callable[[], None]
    ) -> None:
        """Stage files beside originals, roll back on DB failure, then remove staged bytes.

        SQLite and a filesystem cannot share a transaction. A post-commit cleanup
        failure is explicit (503) and leaves .delete-* files for administrator recovery.
        """
        moved: list[tuple[Path, Path]] = []
        try:
            for doc in documents:
                original = self.path(doc.storage_key)
                staged = self.root / f".delete-{uuid4().hex}-{doc.storage_key}"
                original.rename(staged)
                moved.append((original, staged))
            delete_metadata()
            db.commit()
        except Exception as exc:
            db.rollback()
            try:
                for original, staged in reversed(moved):
                    staged.rename(original)
            except OSError as restore_error:
                logger.exception("Failed to restore staged files")
                raise HTTPException(
                    503, "Storage recovery required. Contact the administrator."
                ) from restore_error
            if isinstance(exc, FileNotFoundError):
                raise HTTPException(409, "A stored file is missing; nothing was deleted.") from exc
            if isinstance(exc, OSError):
                raise HTTPException(503, "Could not delete files; nothing was deleted.") from exc
            raise
        try:
            for _, staged in moved:
                staged.unlink()
        except OSError as exc:
            logger.exception("Metadata deleted but staged file cleanup failed")
            raise HTTPException(
                503, "Metadata was deleted, but file cleanup needs administrator attention."
            ) from exc
