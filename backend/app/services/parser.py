"""Standalone parser subprocess. No database, network, or application imports."""

import json
import logging
import sys
from pathlib import Path

from pypdf import PdfReader


class ExtractionFailure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def normalize(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")


IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_SIDE = 2000  # long edge sent for text recognition


def save_image(image, target):
    """Normalize an image for text recognition: RGB PNG, long edge at most MAX_SIDE."""
    image = image.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    image.save(target, "PNG")


def extract(path, media_type, max_pages, max_chars, image_dir=None, max_ocr=0):
    warnings = []
    units = []
    total = 0
    ocr = []  # [{page, file}] images for the app to send to text recognition

    def add(text, page=None):
        nonlocal total
        text = normalize(text)
        total += len(text)
        if total > max_chars:
            raise ExtractionFailure(
                "character_limit",
                "Character limit exceeded. Split the source and upload smaller files.",
            )
        units.append(
            dict(
                position=len(units),
                page_number=page,
                label=f"Page {page}" if page else "Document",
                original_text=text,
            )
        )

    if media_type in IMAGE_TYPES:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()  # rejects truncated or corrupt files
        if image_dir is None:
            raise ExtractionFailure("no_image_dir", "Images cannot be processed here.")
        with Image.open(path) as image:
            save_image(image, Path(image_dir) / "image.png")
        ocr.append({"page": None, "file": "image.png"})
        return dict(
            status="needs_ocr",
            units=[],
            warnings=warnings,
            code="image",
            message="This image needs text recognition.",
            ocr=ocr,
        )
    if media_type == "application/pdf":

        class WarningHandler(logging.Handler):
            def emit(self, record):
                # Do not retain parser messages, which can contain paths or source data.
                if not warnings:
                    warnings.append("PDF structural warnings: compare text with the original.")

        handler = WarningHandler()
        log = logging.getLogger("pypdf")
        log.addHandler(handler)
        try:
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ExtractionFailure(
                    "encrypted_pdf",
                    "Password-protected PDFs are not supported. Upload an unencrypted copy.",
                )
            if len(reader.pages) > max_pages:
                raise ExtractionFailure(
                    "page_limit", "PDF exceeds the page limit. Split it into smaller files."
                )
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                add(text, number)
                if not text.strip() and image_dir is not None and len(ocr) < max_ocr:
                    # Scanned page: keep its largest image for text recognition.
                    try:
                        images = sorted(page.images, key=lambda i: len(i.data), reverse=True)
                        if images:
                            name = f"page-{number}.png"
                            save_image(images[0].image, Path(image_dir) / name)
                            ocr.append({"page": number, "file": name})
                    except Exception:  # noqa: BLE001 - unreadable image: page stays empty
                        warnings.append(f"Page {number}: its image could not be read.")
        finally:
            log.removeHandler(handler)
        empty = [str(u["page_number"]) for u in units if not u["original_text"].strip()]
        if not any(u["original_text"].strip() for u in units):
            return dict(
                status="needs_ocr",
                units=units,
                warnings=warnings,
                code="no_pdf_text",
                message=(
                    "No text layer was found: this looks like a scanned PDF. "
                    "Its pages need text recognition."
                ),
                ocr=ocr,
            )
        if empty and not ocr:
            warnings.append(
                "No usable text on pages "
                + ", ".join(empty)
                + ". These pages may be blank or image-based."
            )
    else:
        add(Path(path).read_text(encoding="utf-8-sig"))
        if not units[0]["original_text"].strip():
            raise ExtractionFailure(
                "empty_content",
                "The source contains only whitespace. Upload a file with usable text.",
            )
    return dict(
        status="extracted", units=units, warnings=warnings, code=None, message=None, ocr=ocr
    )


def run(path, media_type, max_pages, max_chars, image_dir=None, max_ocr=0):
    try:
        return extract(path, media_type, max_pages, max_chars, image_dir, max_ocr)
    except ExtractionFailure as exc:
        code, message = exc.code, exc.message
    except OSError:
        code, message = (
            "unreadable_source",
            "Source file could not be read. Check storage availability and retry.",
        )
    except Exception:
        code, message = (
            "invalid_source",
            "The source could not be parsed. Upload a valid, readable copy.",
        )
    return dict(status="failed", units=[], warnings=[], code=code, message=message)


if __name__ == "__main__":
    image_dir = sys.argv[6] if len(sys.argv) > 6 else None
    max_ocr = int(sys.argv[7]) if len(sys.argv) > 7 else 0
    result = run(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), image_dir, max_ocr)
    Path(sys.argv[5]).write_text(json.dumps(result), encoding="utf-8")
