"""Publishing (snapshot what students see) and notes export to markdown or PDF."""

import re

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Artifact, ArtifactVersion, Syllabus, SyllabusUnit, Workspace, utcnow
from app.services.course_content import KINDS, NOTES, syllabus_units

PUBLISHED_KINDS = [name for name, kind in KINDS.items() if kind.publishable]


class PublishError(Exception):
    pass


def unit_artifacts(db: Session, workspace_id, kinds=PUBLISHED_KINDS) -> dict:
    """{(kind, unit_id): Artifact} for the course's per-unit artifacts with content."""
    rows = db.scalars(
        select(Artifact).where(
            Artifact.workspace_id == workspace_id,
            Artifact.kind.in_(kinds),
            Artifact.current_version > 0,
        )
    )
    return {(a.kind, a.unit_id): a for a in rows}


def publish(db: Session, workspace: Workspace) -> dict:
    syllabus = db.scalar(select(Syllabus).where(Syllabus.workspace_id == workspace.id))
    if syllabus is None or syllabus.status != "approved":
        raise PublishError("Approve the syllabus before publishing.")
    units = syllabus_units(db, syllabus.id)
    found = unit_artifacts(db, workspace.id)
    with_notes = [u for u in units if (NOTES, u.id) in found]
    if not with_notes:
        raise PublishError("Generate notes for at least one unit before publishing.")
    for artifact in found.values():
        artifact.published_version = artifact.current_version
    workspace.published_at = utcnow()
    db.commit()
    return {
        "published_at": workspace.published_at,
        "units_with_notes": len(with_notes),
        "units_without_notes": [u.title for u in units if (NOTES, u.id) not in found],
    }


def version_for(db: Session, artifact: Artifact | None, which: str) -> ArtifactVersion | None:
    if artifact is None:
        return None
    number = artifact.published_version if which == "published" else artifact.current_version
    if not number:
        return None
    return db.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.number == number
        )
    )


def course_units(db: Session, workspace_id) -> list[SyllabusUnit]:
    syllabus = db.scalar(select(Syllabus).where(Syllabus.workspace_id == workspace_id))
    return syllabus_units(db, syllabus.id) if syllabus else []


def export_markdown(db: Session, workspace: Workspace, which: str = "current") -> str:
    """All unit notes (current or published versions) with a source list per unit."""
    units = course_units(db, workspace.id)
    found = unit_artifacts(db, workspace.id, [NOTES])
    meta = [
        workspace.subject or "",
        workspace.learner_level,
        f"{workspace.lesson_duration_minutes} min",
    ]
    out = [f"# {workspace.title}", "", " · ".join(m for m in meta if m), "", "## Syllabus", ""]
    out += [
        f"{i}. {u.title}" + (f": {u.summary}" if u.summary else "") for i, u in enumerate(units, 1)
    ]
    out.append("")
    for unit in units:
        version = version_for(db, found.get((NOTES, unit.id)), which)
        if version is None:
            continue
        out += [version.markdown.strip(), ""]
        if version.citations:
            out += ["### Sources for this unit", ""]
            for label, c in version.citations.items():
                page = f", page {c.get('page')}" if c.get("page") else ""
                excerpt = re.sub(r"\s+", " ", c.get("excerpt", ""))[:160]
                out.append(f"- [{label}] {c.get('document')}{page}: “{excerpt}”")
            out.append("")
    return "\n".join(out)


LATIN1 = str.maketrans(
    {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "...", "•": "-",
     "·": "-", "→": "->", "≤": "<=", "≥": ">=", "×": "x", " ": " "}
)  # fmt: skip


def pdf_text(text: str) -> str:
    """Core PDF fonts cover Latin-1 only: map common punctuation, replace the rest."""
    return text.translate(LATIN1).encode("latin-1", "replace").decode("latin-1")


def export_pdf(markdown: str, title: str) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_title(pdf_text(title))
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    sizes = {"# ": 18, "## ": 14, "### ": 12}

    def write(text: str, size: float = 10.5, style: str = "", indent: float = 0, md=True):
        pdf.set_font("Helvetica", style, size)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(0, size * 0.55, pdf_text(text), new_x="LMARGIN", new_y="NEXT", markdown=md)

    for line in markdown.splitlines():
        stripped = line.strip()
        heading = next((p for p in sizes if stripped.startswith(p)), None)
        if not stripped:
            pdf.ln(2)
        elif heading:
            pdf.ln(3)
            write(stripped[len(heading) :], sizes[heading], "B", md=False)
            pdf.ln(1)
        elif re.match(r"^\|[\s\-|]+\|$", stripped):
            continue  # table separator row
        elif stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            write("   |   ".join(cells), 9.5, md=False)
        elif re.match(r"^([-*]|\d+\.)\s+", stripped):
            marker, rest = stripped.split(None, 1)
            write(f"{'-' if marker in '-*' else marker} {rest}", indent=4)
        else:
            write(stripped)
    return bytes(pdf.output())
