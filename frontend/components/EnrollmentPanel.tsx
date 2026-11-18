"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRequestError } from "./AuthProvider";
import { api, type Enrollment, type StudentList } from "@/lib/api";

export function EnrollmentPanel({ workspaceId }: { workspaceId: string }) {
  const handleError = useRequestError();
  const [students, setStudents] = useState<StudentList | null>(null);
  const [enrolled, setEnrolled] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const base = `/workspaces/${workspaceId}/enrollments`;
  useEffect(() => {
    let active = true;
    Promise.all([
      api<StudentList>("/teacher/students"),
      api<Enrollment[]>(base),
    ])
      .then(([list, enrollments]) => {
        if (!active) return;
        setStudents(list);
        setEnrolled(new Set(enrollments.map((e) => e.student_id)));
        setError("");
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
  }, [base, handleError]);
  async function toggle(studentId: string, add: boolean) {
    setBusy(studentId);
    setError("");
    try {
      await api<void>(`${base}/${studentId}`, {
        method: add ? "PUT" : "DELETE",
      });
      setEnrolled((current) => {
        const next = new Set(current);
        if (add) next.add(studentId);
        else next.delete(studentId);
        return next;
      });
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <section className="panel enrollment-panel" aria-labelledby="enrolled">
      <div className="section-heading">
        <h2 id="enrolled">Students</h2>
        <span className="count">{enrolled.size} enrolled</span>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status" className="muted">
          Loading students…
        </p>
      ) : !students || students.students.length === 0 ? (
        <p className="muted">
          You have no students yet. <Link href="/students">Add students</Link>{" "}
          first, then tick them here.
        </p>
      ) : (
        <fieldset>
          <legend className="sr-only">Students enrolled in this course</legend>
          {students.students.map((s) => (
            <label key={s.id} className="check-row">
              <input
                type="checkbox"
                checked={enrolled.has(s.id)}
                disabled={!!busy}
                onChange={(e) => void toggle(s.id, e.target.checked)}
              />
              <span>
                {s.display_name}
                <small className="cell-sub">{s.email}</small>
              </span>
            </label>
          ))}
        </fieldset>
      )}
    </section>
  );
}
