"""Citation markers: [C n] = course source chunk n, [W n] = web source n (research, later).

A marker is valid only if it refers to a source the caller says is allowed: for generation,
exactly the passages that were retrieved and shown to the model; for edits, the course's
current chunks plus the citations already snapshotted in the previous version.
"""

import re
from dataclasses import dataclass, field

MARKER = re.compile(r"\[([CW])(\d{1,6})\]")
# Sections that state no source facts of their own (lists of terms, kit, blank tables).
UNCITED_SECTIONS = frozenset({"key terms", "summary", "apparatus", "observation table"})


def markers(text: str) -> list[str]:
    return [f"{kind}{number}" for kind, number in MARKER.findall(text)]


@dataclass
class CitationCheck:
    used: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.invalid and bool(self.used)


def check(markdown: str, allowed: set[str], require_per_section: bool = True) -> CitationCheck:
    found = markers(markdown)
    result = CitationCheck(
        used=sorted(set(found) & allowed, key=lambda m: (m[0], int(m[1:]))),
        invalid=sorted(set(found) - allowed, key=lambda m: (m[0], int(m[1:]))),
    )
    if not found:
        result.warnings.append("No citations: nothing ties these notes to the course sources.")
    if require_per_section:
        for heading, body in sections(markdown):
            if heading.lower() in UNCITED_SECTIONS:
                continue
            if not markers(body):
                result.warnings.append(f"Section “{heading}” has no citation.")
    return result


def sections(markdown: str) -> list[tuple[str, str]]:
    """Split on level-2 headings: [(heading, body)]."""
    parts = re.split(r"^## +(.+)$", markdown, flags=re.MULTILINE)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
