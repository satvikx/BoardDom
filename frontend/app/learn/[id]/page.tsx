"use client";
import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Protected, useRequestError } from "@/components/AuthProvider";
import { CitationList } from "@/components/CitationList";
import { Markdown } from "@/components/Markdown";
import { StudyAids } from "@/components/study/StudyAids";
import { StudyCoach } from "@/components/study/StudyCoach";
import { StudyQuiz } from "@/components/study/StudyQuiz";
import { StudyVideo } from "@/components/study/StudyVideo";
import {
  api,
  downloadFile,
  type CourseDetail,
  type PublishedDoc,
  type StudyAidTool,
} from "@/lib/api";

type Tool = "notes" | "coach" | "quiz" | "video" | StudyAidTool;

const TOOLS: { id: Exclude<Tool, "notes">; label: string; hint: string }[] = [
  { id: "video", label: "Video", hint: "Narrated slides" },
  { id: "quiz", label: "Quiz", hint: "Test yourself" },
  { id: "mind_map", label: "Mind map", hint: "See the big picture" },
  { id: "short_notes", label: "Short notes", hint: "Quick revision" },
  { id: "flashcards", label: "Flashcards", hint: "Recall practice" },
  { id: "coach", label: "Exam-prep chat", hint: "Find your gaps" },
];

function StudentCourse({ id }: { id: string }) {
  const handleError = useRequestError();
  const base = `/student/courses/${id}`;
  const [detail, setDetail] = useState<CourseDetail | null>(null);
  const [tool, setTool] = useState<Tool>("notes");
  const [doc, setDoc] = useState<PublishedDoc | null>(null);
  const [docKind, setDocKind] = useState<"notes" | "lab">("notes");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const loadDetail = useCallback(() => api<CourseDetail>(base), [base]);
  const openDoc = useCallback(
    async (unitId: string, kind: "notes" | "lab") => {
      setError("");
      try {
        setDoc(await api<PublishedDoc>(`${base}/units/${unitId}/${kind}`));
        setDocKind(kind);
        setTool("notes");
      } catch (e) {
        setError(handleError(e));
      }
    },
    [base, handleError],
  );
  useEffect(() => {
    let active = true;
    loadDetail()
      .then(async (data) => {
        if (!active) return;
        setDetail(data);
        const first = data.units.find((u) => u.has_notes);
        if (first) {
          const notes = await api<PublishedDoc>(
            `${base}/units/${first.id}/notes`,
          );
          if (active) setDoc(notes);
        }
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [base, loadDetail, handleError]);
  async function toggleStudied(unitId: string, studied: boolean) {
    try {
      await api<void>(`${base}/units/${unitId}/progress`, {
        method: studied ? "PUT" : "DELETE",
      });
      setDetail(await loadDetail());
    } catch (e) {
      setError(handleError(e));
    }
  }
  if (loading)
    return (
      <p className="loading" role="status">
        Loading course…
      </p>
    );
  if (!detail)
    return (
      <>
        <Link className="back-link" href="/learn">
          ← My courses
        </Link>
        <p className="error" role="alert">
          {error || "Course not found."}
        </p>
      </>
    );
  const { course, units } = detail;
  return (
    <>
      <Link className="back-link" href="/learn">
        ← My courses
      </Link>
      <div className="page-heading workspace-heading">
        <p className="eyebrow">{course.subject || "Course"}</p>
        <h1>{course.title}</h1>
        <div className="metadata">
          <span className="capitalize">{course.learner_level}</span>
          <span>{course.lesson_duration_minutes} min sessions</span>
          <span>{course.teacher_name}</span>
          <span>
            {course.units_done} of {course.units_total} units studied
          </span>
        </div>
        {course.description && (
          <p className="description">{course.description}</p>
        )}
      </div>

      <section className="study-tools" aria-labelledby="tools-heading">
        <h2 id="tools-heading">Study tools</h2>
        <div className="tool-grid">
          {TOOLS.map((t) => (
            <button
              key={t.id}
              className={`tool-card${tool === t.id ? " active" : ""}`}
              aria-pressed={tool === t.id}
              onClick={() => setTool(t.id)}
            >
              <strong>{t.label}</strong>
              <small>{t.hint}</small>
            </button>
          ))}
        </div>
      </section>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="workspace-grid">
        <div>
          {tool === "notes" &&
            (doc ? (
              <section className="panel">
                <p className="eyebrow">
                  {docKind === "lab" ? "Lab manual" : "Unit notes"} · version{" "}
                  {doc.version}
                </p>
                <Markdown
                  text={doc.markdown}
                  citations={Object.keys(doc.citations)}
                />
                <CitationList citations={doc.citations} />
              </section>
            ) : (
              <div className="empty-state compact">
                <h3>Pick a unit</h3>
                <p>Choose a unit on the right to read its notes.</p>
              </div>
            ))}
          {tool === "coach" && <StudyCoach base={base} />}
          {tool === "quiz" && <StudyQuiz base={base} units={units} />}
          {tool === "video" && <StudyVideo base={base} units={units} />}
          {(tool === "mind_map" ||
            tool === "short_notes" ||
            tool === "flashcards") && (
            <StudyAids base={base} units={units} tool={tool} />
          )}
        </div>
        <aside>
          <section className="panel">
            <div className="section-heading">
              <h2>Syllabus</h2>
              <span className="count">{units.length} units</span>
            </div>
            <ol className="unit-list">
              {units.map((u) => (
                <li key={u.id}>
                  <h3>{u.title}</h3>
                  {u.summary && <p className="muted">{u.summary}</p>}
                  <div className="button-row">
                    {u.has_notes ? (
                      <button
                        className="text-button"
                        onClick={() => void openDoc(u.id, "notes")}
                      >
                        Read notes
                      </button>
                    ) : (
                      <span className="muted small-print">
                        Notes coming soon
                      </span>
                    )}
                    {u.has_lab_manual && (
                      <button
                        className="text-button"
                        onClick={() => void openDoc(u.id, "lab")}
                      >
                        Lab manual
                      </button>
                    )}
                  </div>
                  <label className="check-row small-print">
                    <input
                      type="checkbox"
                      checked={u.studied}
                      onChange={(e) =>
                        void toggleStudied(u.id, e.target.checked)
                      }
                    />
                    I have studied this unit
                  </label>
                </li>
              ))}
            </ol>
            <div className="button-row">
              <button
                className="secondary"
                onClick={() =>
                  void downloadFile(`${base}/export?format=pdf`, "notes.pdf")
                }
              >
                Download notes (PDF)
              </button>
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}

export default function StudentCoursePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <Protected roles={["student"]}>
      <StudentCourse id={id} />
    </Protected>
  );
}
