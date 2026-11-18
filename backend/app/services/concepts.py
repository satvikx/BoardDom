"""Concept graph: concepts with prerequisite edges, built from the syllabus and unit notes.

The model proposes concepts and edges; this module keeps only a clean DAG: unique names,
edges between known concepts, no self-loops, and no cycles (an edge closing a cycle is dropped).
"""

import re
from collections import defaultdict

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Artifact,
    ArtifactVersion,
    Concept,
    ConceptEdge,
    Job,
    SyllabusUnit,
    Workspace,
)
from app.services.course_content import (
    DATA_NOT_INSTRUCTIONS,
    NOTES,
    approved_syllabus,
    course_header,
    syllabus_units,
    units_block,
)
from app.services.jobs import JobFailed

MAX_CONCEPTS = 60


class ConceptItem(BaseModel):
    name: str
    description: str
    unit_title: str


class EdgeItem(BaseModel):
    prerequisite: str
    concept: str


class ConceptGraphDraft(BaseModel):
    concepts: list[ConceptItem]
    edges: list[EdgeItem]


INSTRUCTIONS = (
    "You map the concepts of a course. From the syllabus units and the notes digest, list the "
    "important concepts (5 to 40), each with a one-sentence description and the exact title of "
    "the unit that teaches it. Then list prerequisite edges: `prerequisite` must be understood "
    "before `concept`. Use concept names exactly as listed. Only add an edge when the "
    f"dependency is real. {DATA_NOT_INSTRUCTIONS}"
)


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def notes_digest(db: Session, workspace_id, units) -> str:
    lines = []
    for unit in units:
        version = db.scalar(
            select(ArtifactVersion)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                Artifact.workspace_id == workspace_id,
                Artifact.kind == NOTES,
                Artifact.unit_id == unit.id,
                ArtifactVersion.number == Artifact.current_version,
            )
        )
        if version is None:
            continue
        headings = re.findall(r"^## (.+)$", version.markdown, re.M)
        terms = re.findall(r"^- \*\*(.+?)\*\*", version.markdown, re.M)
        headings = [h for h in headings if h not in ("Key terms", "Summary")]
        lines.append(f"- {unit.title}: sections {'; '.join(headings)}; terms {'; '.join(terms)}")
    return "NOTES DIGEST\n" + ("\n".join(lines) or "(no notes yet)") + "\nEND DIGEST"


def clean_graph(draft: ConceptGraphDraft) -> tuple[list[ConceptItem], list[tuple[str, str]], int]:
    """Unique concepts, valid acyclic edges. Returns (concepts, edges as keys, dropped edges)."""
    concepts: dict[str, ConceptItem] = {}
    for item in draft.concepts:
        k = key(item.name)
        if k and k not in concepts and len(concepts) < MAX_CONCEPTS:
            concepts[k] = item
    children: dict[str, set[str]] = defaultdict(set)

    def reaches(start: str, target: str) -> bool:
        stack, seen = [start], set()
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node not in seen:
                seen.add(node)
                stack.extend(children[node])
        return False

    edges, dropped = [], 0
    for edge in draft.edges:
        p, c = key(edge.prerequisite), key(edge.concept)
        if p not in concepts or c not in concepts or p == c or c in children[p]:
            dropped += 1
            continue
        if reaches(c, p):  # p -> c would close a cycle
            dropped += 1
            continue
        children[p].add(c)
        edges.append((p, c))
    return list(concepts.values()), edges, dropped


def build_concepts(provider):
    def run(db: Session, job: Job, report) -> str:
        workspace = db.get(Workspace, job.workspace_id)
        syllabus = approved_syllabus(db, workspace.id)
        units = syllabus_units(db, syllabus.id)
        report(0, 1)
        prompt = (
            f"{course_header(workspace)}\n\n{units_block(units)}\n\n"
            f"{notes_digest(db, workspace.id, units)}"
        )
        draft, _ = provider.structured(
            INSTRUCTIONS, prompt, ConceptGraphDraft, purpose="concept_graph"
        )
        items, edges, dropped = clean_graph(draft)
        if not items:
            raise JobFailed("The AI returned no concepts. Try again.")
        by_title = {key(u.title): u.id for u in units}
        db.execute(delete(Concept).where(Concept.workspace_id == workspace.id))
        rows = {}
        for position, item in enumerate(items):
            row = Concept(
                workspace_id=workspace.id,
                key=key(item.name),
                name=item.name.strip()[:200],
                description=item.description.strip(),
                unit_id=by_title.get(key(item.unit_title)),
                position=position,
            )
            db.add(row)
            rows[row.key] = row
        db.flush()
        for p, c in edges:
            db.add(
                ConceptEdge(
                    workspace_id=workspace.id,
                    prerequisite_id=rows[p].id,
                    concept_id=rows[c].id,
                )
            )
        db.commit()
        report(1, 1)
        note = f" Dropped {dropped} invalid or circular link(s)." if dropped else ""
        return f"Mapped {len(items)} concepts and {len(edges)} prerequisite links.{note}"

    return run


def load_graph(db: Session, workspace_id):
    concepts = list(
        db.scalars(
            select(Concept).where(Concept.workspace_id == workspace_id).order_by(Concept.position)
        )
    )
    edges = list(db.scalars(select(ConceptEdge).where(ConceptEdge.workspace_id == workspace_id)))
    return concepts, edges


def levels(concepts, edges) -> dict:
    """Longest prerequisite chain above each concept (0 = no prerequisites)."""
    parents = defaultdict(list)
    for e in edges:
        parents[e.concept_id].append(e.prerequisite_id)
    memo: dict = {}

    def depth(node, trail=()):
        if node in memo:
            return memo[node]
        if node in trail:  # Defensive: stored graphs are acyclic.
            return 0
        memo[node] = 1 + max((depth(p, (*trail, node)) for p in parents[node]), default=-1)
        return memo[node]

    return {c.id: depth(c.id) for c in concepts}


def known_concepts(text: str, concepts) -> set:
    """Concepts the student mentions (whole-word, case-insensitive name match)."""
    spoken = f" {key(text)} "
    return {c.id for c in concepts if c.key and f" {c.key} " in spoken}


def prioritize(concepts, edges, known: set) -> list:
    """Gaps in study order: ready-now first, then by how many concepts depend on them."""
    parents, dependents = defaultdict(set), defaultdict(int)
    for e in edges:
        parents[e.concept_id].add(e.prerequisite_id)
        dependents[e.prerequisite_id] += 1
    depth = levels(concepts, edges)
    gaps = [c for c in concepts if c.id not in known]

    def rank(c):
        ready = parents[c.id] <= known
        return (0 if ready else 1, depth[c.id], -dependents[c.id], c.position)

    return sorted(gaps, key=rank)


def graph_out(db: Session, workspace_id):
    from app.schemas.course import ConceptGraphOut, ConceptOut

    concepts, edges = load_graph(db, workspace_id)
    depth = levels(concepts, edges)
    parents = defaultdict(list)
    for e in edges:
        parents[e.concept_id].append(e.prerequisite_id)
    titles = dict(
        db.execute(
            select(SyllabusUnit.id, SyllabusUnit.title).where(
                SyllabusUnit.id.in_([c.unit_id for c in concepts if c.unit_id])
            )
        ).all()
    )
    return ConceptGraphOut(
        concepts=[
            ConceptOut(
                id=c.id,
                name=c.name,
                description=c.description,
                unit_id=c.unit_id,
                unit_title=titles.get(c.unit_id),
                level=depth[c.id],
                prerequisite_ids=parents[c.id],
            )
            for c in sorted(concepts, key=lambda c: (depth[c.id], c.position))
        ],
        edge_count=len(edges),
    )
