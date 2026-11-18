"""Deterministic generators for the offline FakeProvider (demo mode and tests).

They read the same prompt format the real model gets (course header, unit header, numbered
passages) and build plausible output from the passages themselves, citing only real labels.
"""

import re

from app.services.course_content import parse_notes, parse_passages

HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.M)


def clean(text: str) -> str:
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def sentences(text: str) -> list[str]:
    body = HEADING.sub("", text)  # headings become titles, not part of the prose
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean(body)) if s.strip()]


def title_of(text: str, fallback: str) -> str:
    found = HEADING.search(text)
    if found:
        return found.group(1).strip()[:80]
    words = clean(text).split()[:6]
    return " ".join(words).rstrip(".,;:").capitalize()[:80] or fallback


def field(prompt: str, name: str) -> str:
    found = re.search(rf"^{name}: (.*)$", prompt, re.M)
    return found.group(1).strip() if found else ""


def demo_syllabus(instructions: str, prompt: str) -> dict:
    passages = parse_passages(prompt)
    course = field(prompt, "Course title") or "this course"
    if not passages:
        return {"units": []}
    count = min(4, len(passages))
    groups = [passages[i::count] for i in range(count)]
    weeks = int((field(prompt, "Length") or f"{count} weeks").split()[0])
    required = [t.strip() for t in field(prompt, "Must include topics").split(";") if t.strip()]
    findings = WEB_FINDING.findall(prompt)  # [(n, url, text)]
    units = []
    for number, group in enumerate(groups, start=1):
        first = group[0][2]
        topics = [title_of(text, f"Topic {i}") for i, (_, _, text) in enumerate(group, 1)]
        summary = (sentences(first) or [f"Core ideas of {course}."])[0][:200]
        sources = [f"C{n}" for n, _, _ in group]
        for n, _, text in findings:
            if set(clean(text).lower().split()) & set(" ".join(topics).lower().split()):
                sources.append(f"W{n}")
        units.append(
            {
                "title": f"Unit {number}: {title_of(first, f'Part {number}')}",
                "summary": summary,
                "topics": list(dict.fromkeys(topics))[:5],
                "weeks": max(1, weeks // count),
                "sources": sources,
            }
        )
    for i, topic in enumerate(required):  # a cooperative model covers every required topic
        if not any(topic.lower() in " ".join(u["topics"]).lower() for u in units):
            units[i % len(units)]["topics"].append(topic)
    if findings and not any(s.startswith("W") for u in units for s in u["sources"]):
        units[0]["sources"].append(f"W{findings[0][0]}")
    return {"units": units}


WEB_FINDING = re.compile(r"^\[W(\d+)\] \((.*?)\)\n(.*)$", re.M)


def demo_unit_notes(instructions: str, prompt: str) -> dict:
    passages = parse_passages(prompt)
    topics = [t.strip() for t in field(prompt, "Topics").split(";") if t.strip()]
    first = passages[0][0] if passages else 0
    sections = []
    for index, (ordinal, _, text) in enumerate(passages[:3], start=1):
        said = sentences(text) or [clean(text)[:200]]
        explanation = " ".join(said[:2])[:400]
        example = None
        if len(said) > 2:
            example = f"Apply this idea: {said[2][:200]} [C{ordinal}]"
        sections.append(
            {
                "heading": title_of(text, f"Key idea {index}"),
                "explanation": f"{explanation} [C{ordinal}]",
                "worked_example": example,
            }
        )
    key_terms = [
        {"term": topic, "definition": f"A topic of this unit, explained in the sources [C{first}]."}
        for topic in (topics or ["Core idea"])[:4]
    ]
    covered = ", ".join(topics[:3]) or "the unit's core ideas"
    return {
        "sections": sections,
        "key_terms": key_terms,
        "summary": f"(Demo mode) This unit covered {covered} [C{first}].",
    }


UNIT_LINE = re.compile(r"^- (.*?) \| topics: (.*)$", re.M)


def parse_units(prompt: str) -> list[tuple[str, list[str]]]:
    """[(unit title, topics)] from a prompt built with course_content.units_block."""
    return [
        (title.strip(), [t.strip() for t in topics.split(";") if t.strip()])
        for title, topics in UNIT_LINE.findall(prompt)
    ]


def demo_lab(instructions: str, prompt: str) -> dict:
    passages = parse_passages(prompt)
    unit = field(prompt, "Unit title") or "this unit"
    first = passages[0][0] if passages else 0
    facts = [(n, s) for n, _, text in passages for s in sentences(text)][:6]
    procedure = ["Put on safety glasses and read every step before starting."]
    procedure += [f"Investigate: {s} [C{n}]" for n, s in facts[:3]]
    procedure.append("Record each reading in the observation table and tidy the bench.")
    return {
        "aim": f"(Demo mode) To investigate {unit.lower()} using the course sources [C{first}].",
        "apparatus": ["Notebook and pencil", "Stopwatch", "Ruler", "Safety glasses"],
        "procedure": procedure,
        "observation_columns": ["Trial", "Observation", "Measurement", "Remarks"],
        "observation_rows": 5,
        "viva_questions": [
            {"question": f"What does this statement tell you: {s[:80]}?", "answer": f"{s} [C{n}]"}
            for n, s in facts[:4]
        ],
    }


def demo_lesson(instructions: str, prompt: str) -> dict:
    passages = parse_passages(prompt)
    unit = field(prompt, "Unit title") or "this unit"
    length = int((field(prompt, "Session length") or "40 minutes").split()[0])
    first = passages[0][0] if passages else 0
    teach = max(length - 20, 5)
    return {
        "sessions": [
            {
                "title": f"Introducing {unit}",
                "objectives": [f"Explain the main idea of {unit} [C{first}]", "Give one example"],
                "activities": [
                    {"minutes": 5, "activity": "Warm-up question on prior knowledge"},
                    {"minutes": teach, "activity": f"Teach from the unit notes [C{first}]"},
                    {"minutes": 10, "activity": "Pairs practice with a worked example"},
                    {"minutes": length - 15 - teach, "activity": "Exit ticket and wrap-up"},
                ],
                "assessment": "Three-question exit ticket on the key terms.",
            }
        ]
    }


def demo_rubric(instructions: str, prompt: str) -> dict:
    pattern = re.findall(r"([^,]+?) (\d+)%", field(prompt, "Assessment pattern"))
    if pattern:  # follow the wizard's assessment pattern
        criteria = [(name.strip(), 0) for name, _ in pattern]
        weights = [int(w) for _, w in pattern]
    else:
        units = parse_units(prompt) or [("Course content", [])]
        names = [title.split(":", 1)[-1].strip() for title, _ in units][:3]
        criteria = [("Understanding of " + name, 0) for name in names]
        criteria += [("Use of evidence and sources", 0), ("Communication", 0)]
        weight = 100 // len(criteria)
        weights = [weight] * len(criteria)
        weights[0] += 100 - sum(weights)
    return {
        "criteria": [
            {
                "criterion": name,
                "weight_percent": w,
                "excellent": "Accurate, complete and well explained, with examples.",
                "good": "Mostly accurate with minor gaps.",
                "satisfactory": "Basic understanding with several gaps.",
                "needs_work": "Major misunderstandings or missing work.",
            }
            for (name, _), w in zip(criteria, weights, strict=True)
        ]
    }


def demo_concepts(instructions: str, prompt: str) -> dict:
    """Topics become concepts; each topic needs the previous one (also across units)."""
    concepts, edges, previous = [], [], None
    for title, topics in parse_units(prompt):
        for topic in topics or [title.split(":", 1)[-1].strip()]:
            concepts.append(
                {"name": topic, "description": f"(Demo) Part of {title}.", "unit_title": title}
            )
            if previous:
                edges.append({"prerequisite": previous, "concept": topic})
            previous = topic
    return {"concepts": concepts, "edges": edges}


CITE = re.compile(r"\[C\d{1,6}\]")
LONG_WORD = re.compile(r"[A-Za-z][A-Za-z-]{4,}")


def note_facts(prompt: str) -> list[tuple[str, str, str]]:
    """[(unit title, sentence without labels, label)] for cited sentences in the notes."""
    facts = []
    for title, body in parse_notes(prompt):
        for line in body.splitlines():
            # Prose only: skip headings, key-term bullets, tables and the demo summary.
            if line.startswith(("#", "-", "|")) or "(Demo mode)" in line:
                continue
            labels = CITE.findall(line)
            if not labels:
                continue
            text = line.replace("**Worked example.**", "").replace("Apply this idea:", "")
            for sentence in re.split(r"(?<=[.!?])\s+", clean(CITE.sub("", text))):
                sentence = sentence.strip(" .")
                if len(sentence.split()) >= 4 and not sentence.endswith(":"):
                    # A paragraph's citation supports each of its sentences.
                    facts.append((title, sentence + ".", labels[-1]))
    return list(dict.fromkeys(facts))


def demo_coach(instructions: str, prompt: str) -> dict:
    passages = parse_passages(prompt)
    if not passages:
        return {"in_scope": False, "answer": "", "checklist": []}
    known = field(prompt, "KNOWN CONCEPTS")
    gaps = re.findall(r"^\d+\. (.+?)(?: \(needs: .*\))?$", prompt, re.M)

    def passage_for(topic: str):
        """The retrieved passage that mentions the topic, else the best match."""
        words = set(clean(topic).lower().split())
        return next(
            (p for p in passages if words and words <= set(clean(p[2]).lower().split())),
            passages[0],
        )

    opening = f"You already know {known}." if known and known != "none named" else ""
    focus = gaps[0] if gaps else title_of(passages[0][2], "this topic")
    n, _, text = passage_for(focus)
    answer = (
        f"(Demo mode) {opening} Next, focus on {focus}: {(sentences(text) or [''])[0]} [C{n}]"
    ).replace("  ", " ")
    checklist = []
    for gap in gaps[:5] or [focus]:
        n, _, text = passage_for(gap)
        checklist.append(
            {"item": gap, "why": f"{(sentences(text) or ['Covered in the course'])[0]} [C{n}]"}
        )
    return {"in_scope": True, "answer": answer, "checklist": checklist}


def demo_quiz(instructions: str, prompt: str) -> dict:
    facts = note_facts(prompt)
    pool = list(dict.fromkeys(w.lower() for _, s, _ in facts for w in LONG_WORD.findall(s)))
    pool += ["structure", "pattern", "balance", "network", "surface"]
    questions = []
    for i, (_, sentence, label) in enumerate(facts):
        words = [w for w in LONG_WORD.findall(sentence) if w.lower() not in STOP_SHORT]
        if not words:
            continue
        answer = max(words, key=len)
        others = [w for w in pool if w != answer.lower()][i : i + 3]
        if len(others) < 3:
            continue
        options = others[:]
        options.insert(i % 4, answer.lower())
        questions.append(
            {
                "question": "Fill the gap: " + sentence.replace(answer, "_____", 1),
                "options": options,
                "answer_index": i % 4,
                "explanation": f"(Demo mode) The notes say: {sentence} {label}",
            }
        )
    count = int(field(prompt, "Number of questions") or 5)
    return {"questions": questions[:count]}


STOP_SHORT = frozenset({"example", "about", "which", "their", "there", "these"})


def demo_mind_map(instructions: str, prompt: str) -> dict:
    notes = parse_notes(prompt)
    title, body = notes[0] if notes else ("Unit", "")
    branches = []
    for heading, text in re.findall(r"^## (.+)\n+(.+)$", body, re.M):
        if heading in ("Key terms", "Summary"):
            continue
        children = [" ".join(s.split()[:5]) for s in sentences(CITE.sub("", text))[:3]]
        branches.append({"label": heading, "children": children or ["Key idea"]})
    terms = re.findall(r"^- \*\*(.+?)\*\*", body, re.M)
    if terms:
        branches.append({"label": "Key terms", "children": terms[:5]})
    return {"central": title.split(":", 1)[-1].strip(), "branches": branches}


def demo_short_notes(instructions: str, prompt: str) -> dict:
    return {"points": [f"{s} {label}" for _, s, label in note_facts(prompt)[:8]]}


def demo_flashcards(instructions: str, prompt: str) -> dict:
    cards = []
    for _, body in parse_notes(prompt):
        for term, definition in re.findall(r"^- \*\*(.+?)\*\*: (.+)$", body, re.M):
            cards.append({"front": f"What is {term}?", "back": definition})
    for _, sentence, label in note_facts(prompt)[:4]:
        cards.append(
            {"front": f"Explain: {' '.join(sentence.split()[:6])}…", "back": f"{sentence} {label}"}
        )
    return {"cards": cards[:10]}


def demo_video_script(instructions: str, prompt: str) -> dict:
    notes = parse_notes(prompt)
    title, body = notes[0] if notes else ("This unit", "")
    sections = [
        (h, t) for h, t in re.findall(r"^## (.+)\n+(.+)$", body, re.M) if h not in ("Key terms",)
    ]
    slides = [
        {
            "title": title,
            "bullets": [h for h, _ in sections if h != "Summary"][:4],
            "narration": f"This short demo video walks through {title}.",
        }
    ]
    for heading, text in sections[:4]:
        said = sentences(CITE.sub("", text))
        slides.append(
            {
                "title": heading,
                "bullets": [" ".join(s.split()[:6]) for s in said[:3]],
                "narration": " ".join(said[:2]) or heading,
            }
        )
    return {"slides": slides}


def demo_research_plan(instructions: str, prompt: str) -> dict:
    course = field(prompt, "Course title") or "course"
    required = [t.strip() for t in field(prompt, "Must include topics").split(";") if t.strip()]
    base = [f"{course} syllabus", f"{course} key concepts", f"{course} teaching resources"]
    return {"queries": [*base, *[f"{course} {t}" for t in required[:2]]][:4]}


def install(provider) -> None:
    builders = getattr(provider, "structured_builders", None)
    if builders is None:
        return
    builders.setdefault("SyllabusDraft", demo_syllabus)
    builders.setdefault("UnitNotesDraft", demo_unit_notes)
    builders.setdefault("LabManualDraft", demo_lab)
    builders.setdefault("LessonPlanDraft", demo_lesson)
    builders.setdefault("RubricDraft", demo_rubric)
    builders.setdefault("ConceptGraphDraft", demo_concepts)
    builders.setdefault("CoachReply", demo_coach)
    builders.setdefault("QuizDraft", demo_quiz)
    builders.setdefault("MindMapDraft", demo_mind_map)
    builders.setdefault("ShortNotesDraft", demo_short_notes)
    builders.setdefault("FlashcardsDraft", demo_flashcards)
    builders.setdefault("VideoScript", demo_video_script)
    builders.setdefault("ResearchPlan", demo_research_plan)
