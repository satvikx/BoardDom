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


def extract(path, media_type, max_pages, max_chars):
    warnings = []
    units = []
    total = 0

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
                add(page.extract_text() or "", number)
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
                    "No usable text was found. Image-only PDFs require OCR, "
                    "which is not available yet. Upload a text-based PDF or text file."
                ),
            )
        if empty:
            warnings.append(
                "No usable text on pages "
                + ", ".join(empty)
                + ". These pages may be blank or image-based; OCR is not available yet."
            )
    else:
        add(Path(path).read_text(encoding="utf-8-sig"))
        if not units[0]["original_text"].strip():
            raise ExtractionFailure(
                "empty_content",
                "The source contains only whitespace. Upload a file with usable text.",
            )
    return dict(status="extracted", units=units, warnings=warnings, code=None, message=None)


def run(path, media_type, max_pages, max_chars):
    try:
        return extract(path, media_type, max_pages, max_chars)
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
    result = run(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
    Path(sys.argv[5]).write_text(json.dumps(result), encoding="utf-8")
