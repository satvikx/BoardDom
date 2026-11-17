Bro, Boardom has a strong hackathon angle. I’d center it on **“Upload what you teach. Get something students can learn from—and teachers can verify.”**

Images and slides will make the demo appealing, but your strongest differentiator is **turning one source into a connected teaching package, with evidence and teacher control.** That fits the brief better than a collection of unrelated AI generators.

Here’s a layered strategy you can turn into your build plan.

## 1. Define the requirements before building

Use one primary user for the hackathon: **a teacher preparing an upcoming lesson.**

The main journey should be:

> Create a lesson workspace → upload notes → review extracted content → choose learning level → generate artifacts → edit and approve → export.

### Must meet the challenge

| Requirement | What Boardom should do |
|---|---|
| Ingest material | Accept pasted text, Markdown, and text-based PDFs |
| Generate multiple artifacts | Lesson plans, rubrics, flashcards, and quiz banks |
| Calibrate learning level | Set learner level, prerequisites, and Bloom’s targets |
| Support review | Let teachers edit, regenerate, and approve outputs |
| Export | Produce clean Markdown, structured JSON, and a printable package |
| Demonstrate quality | Include 2–3 curated source files from one subject |

**Keep learner difficulty and Bloom’s level separate.** “Advanced” concerns the knowledge and complexity required; Bloom’s concerns the type of thinking. An introductory student can still analyze a simple example.

### Make “done” concrete

Your MVP works when a teacher can:

- Upload a PDF and correct the extracted text.
- Generate all four required artifact types.
- See answers and explanations for quiz questions.
- Trace generated material to source passages.
- Edit an artifact and export the edited version.
- Refresh the browser without losing their work.

## 2. Build the basic product before adding AI

First, make the complete workflow work with sample outputs. This prevents the demo from becoming a prompt box with nowhere useful to put the response.

| Feature | Minimum implementation |
|---|---|
| Authentication | Simple email/password login with secure session handling |
| Dashboard | List lesson workspaces and their status |
| Workspace | Title, subject, learner level, lesson duration |
| Upload | Store source files and show upload progress/errors |
| Source preview | Display extracted text with page references |
| Artifact editor | Render structured fields with editable text |
| Review states | Draft → reviewed → approved |
| Export | Markdown, JSON, and browser print layout |

For the interface, use three main areas:

**Sources | Artifact editor | Preview**

Keep the level, duration, and generation controls above the editor. Avoid building a complicated freeform canvas during the hackathon.

## 3. Add a reliable AI generation layer

Instead of sending the entire document to separate prompts for every feature, create a shared intermediate representation:

```text
Source documents
    ↓
Extracted text with page/section references
    ↓
Teacher-reviewed content
    ↓
Concepts, definitions, prerequisites, learning objectives
    ↓
Artifact generation
    ↓
Validation and teacher review
    ↓
Export package
```

That shared concept and objective map helps the lesson plan, quiz, flashcards, and rubric agree with each other.

### Generate structured artifacts

| Artifact | Suggested fields |
|---|---|
| Lesson plan | Objectives, prerequisites, timed activities, checks for understanding, exit ticket |
| Quiz bank | Question, type, answer, explanation, distractor rationale, Bloom’s level, source references |
| Flashcards | Front, back, concept, source references |
| Rubric | Task, criteria, performance levels, descriptors, points |

Use **Pydantic models in FastAPI** to validate model outputs before saving them. Handle invalid output with a bounded retry and a clear error state.

For review, add targeted controls:

- “Make this question easier.”
- “Replace this example.”
- “Regenerate only this section.”
- “Explain why this is labeled Analyze.”

Targeted regeneration is more useful than repeatedly replacing the entire package.

## 4. Pick standout features with a clear priority

These are brainstorming options; build the first two before taking on the rest.

| Idea | What the teacher sees | Why it stands out | Effort |
|---|---|---|---|
| **Source-linked artifacts** | Click a question or claim to reveal its supporting passage | Makes outputs reviewable and trustworthy | Medium |
| **Misconception-aware quizzes** | Each wrong answer includes the misunderstanding it tests | Shows teaching value beyond basic generation | Medium |
| **Learning alignment view** | Objectives mapped to activities and assessment questions | Exposes objectives that aren’t actually assessed | Medium |
| **Interactive concept lab** | A small simulation generated from the lesson topic | Gives you a memorable live demo | Medium–high |
| **Differentiated lesson packs** | Support, standard, and extension versions of one activity | Helps teach mixed-ability classrooms | Medium |
| **Handwritten-note review** | Original photo beside editable transcription; uncertain passages flagged | Supports real teacher workflows | Medium–high |
| **Version comparison** | Highlight what changed between two artifact versions | Makes AI revisions easier to review | Medium |
| **Student study mode** | Practice flashcards and quizzes with explanations | Reuses existing artifacts in an interactive experience | Medium |

### My recommended signature feature: “Show me why”

Every quiz question has a small review panel:

> **Learning objective:** Trace the steps of binary search.  
> **Bloom’s target:** Apply.  
> **Source:** Notes, page 3.  
> **Answer explanation:** …  
> **Distractor rationale:** This option reflects confusing an index with a value.

This makes the platform feel like an educational tool designed for teachers.

Source references must point to real extracted passages. A valid reference alone does not prove the generated claim is supported, so keep the teacher review step.

### Your visual wow feature: one interactive concept lab

For a Data Structures demo, let a teacher generate a **binary search explorer**:

- Students choose a target number.
- They step through each comparison.
- The current search interval changes visually.
- Before each step, they predict which half remains.

Use predefined interactive components populated with validated data. This is far more manageable for a hackathon than letting a model generate and execute arbitrary application code.

Other possible templates:

- Sorting algorithm stepper.
- Supply-and-demand slider.
- Cell structure labeling exercise.
- Timeline with revealable events.
- Graph traversal explorer.

**Build one template exceptionally well.** Expand the template library later.

## 5. Treat media generation as an enhancement layer

Your original ideas fit here, once the required artifacts work.

### Slides

Generate a structured slide outline first:

- Slide title.
- Key points.
- Speaker notes.
- Suggested visual.
- Source references.

Then render it through a fixed slide template. Start with a presentation view; add actual `.pptx` export if time allows.

### Graphs

Generate graphs only from:

- Data supplied in the source.
- Teacher-entered data.
- Clearly labeled illustrative data.

Don’t let a polished chart imply that invented numbers came from the textbook.

### Images and diagrams

Prioritize concept diagrams, labeled processes, and comparison illustrations. These usually contribute more to teaching than decorative images.

### Animations

Start with step-based transitions in a known component. Full video generation adds latency and complexity without helping you meet the core brief.

### Handwriting

Make this a separate ingestion option:

> Upload photo → transcribe → flag uncertainty → teacher corrects → use the normal generation pipeline.

Never silently guess unreadable numbers, formulas, or labels.

## 6. Architecture with Next.js, FastAPI, and SQLite

Your proposed stack is enough for a hackathon.

```text
Next.js
  Dashboard, upload, source viewer, editors, interactive templates
       │
       ▼
FastAPI
  Authentication, extraction, generation, validation, exports
       │
       ├── SQLite: users, workspaces, sources, artifacts, jobs
       ├── Local file storage: uploads and generated exports
       └── AI provider: structured generation and optional vision
```

Use **SQLAlchemy + Alembic** with SQLite so your data layer can evolve without a rewrite.

### Minimal data model

| Entity | Purpose |
|---|---|
| `User` | Account and password hash |
| `Workspace` | Lesson settings and ownership |
| `SourceDocument` | Uploaded file and extraction status |
| `SourceChunk` | Extracted text, page/section, stable identifier |
| `Artifact` | Type, structured content, review status |
| `ArtifactVersion` | Previous generated or edited versions |
| `GenerationJob` | Progress, failures, and generated artifact IDs |

Associate every workspace with its owner and check ownership on every read, edit, and download.

### A few implementation choices that save time

- **One authentication owner:** let FastAPI handle authentication and use secure, HttpOnly cookies.
- **Same-origin routing:** proxy backend requests through the app’s domain to simplify cookie behavior.
- **Durable job status:** save generation progress in SQLite and let the frontend poll it.
- **Simple background execution:** fine for the demo, but handle interrupted jobs explicitly; in-process work won’t survive a server restart.
- **No vector database initially:** for a few short documents, start with section-based chunks and direct context selection.
- **Separate teacher/student exports:** keep answer keys and teaching notes out of student handouts.

## 7. Build in this order

Each layer should produce something you can demo before you move to the next.

| Layer | Build | Completion checkpoint |
|---|---|---|
| **1 — Foundation** | Auth, database, workspaces, uploads | User can save and reopen a workspace |
| **2 — Content pipeline** | PDF/Markdown extraction, source preview, corrections | Teacher can review usable source text |
| **3 — Required artifacts** | Four generators, schemas, editors, exports | Complete package can be generated and downloaded |
| **4 — Review quality** | Source links, targeted regeneration, approval | Teacher can verify and improve individual outputs |
| **5 — Differentiation** | Misconception-aware questions, alignment view | Demo shows clear pedagogical value |
| **6 — Wow factor** | One interactive template | Students can interact with a generated learning activity |
| **7 — Stretch** | Handwriting, slides, extra media | Add only when previous layers are stable |

If time gets tight, cut full PowerPoint export, image generation, handwriting, and extra interactive templates first. Preserve the four required artifacts and the review experience.

## 8. Design the demo around one coherent subject

I’d choose **Data Structures**, with three short sources:

1. Arrays and linear search.
2. Binary search and its prerequisites.
3. Comparing search complexity.

That gives you a natural connection between source material, questions, diagrams, and the interactive explorer.

A strong demo sequence:

1. Upload the notes.
2. Select “Introductory learners, 40 minutes, Understand + Apply.”
3. Generate the teaching package.
4. Open a question and show its source passage.
5. Show how a wrong answer reveals a misconception.
6. Change one question to an Analyze task and review the revision.
7. Launch the binary search explorer.
8. Export the student handout and teacher answer key.

Before presenting, verify that the demo sources produce correct answers, the lesson timings add up, the source links work, and exports include teacher edits.

**The Boardom pitch:** “From messy teaching notes to a source-linked lesson, assessment, and interactive activity—with the teacher in control.”