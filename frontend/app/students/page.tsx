"use client";
import { useEffect, useState, type FormEvent } from "react";
import { Protected, useRequestError } from "@/components/AuthProvider";
import { TempPassword } from "@/components/TempPassword";
import { api, formatDateTime, type Student, type StudentList } from "@/lib/api";

type Created = {
  student: Student;
  temporary_password: string;
  used: number;
  limit: number;
};

function StudentsView() {
  const handleError = useRequestError();
  const [data, setData] = useState<StudentList | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [created, setCreated] = useState<Created | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    api<StudentList>("/teacher/students")
      .then((result) => {
        if (active) {
          setData(result);
          setError("");
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
  }, [handleError, refresh]);
  function begin(action: string) {
    setBusy(action);
    setError("");
    setSuccess("");
  }
  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    begin("create");
    try {
      const result = await api<Created>("/teacher/students", {
        method: "POST",
        body: JSON.stringify({
          display_name: form.get("display_name"),
          email: form.get("email"),
        }),
      });
      setCreated(result);
      formElement.reset();
      setRefresh((n) => n + 1);
    } catch (e) {
      setError(handleError(e));
      setRefresh((n) => n + 1);
    } finally {
      setBusy("");
    }
  }
  async function remove(student: Student) {
    if (
      !window.confirm(
        `Remove ${student.display_name} (${student.email})?\n\nThis deletes the student's account and removes them from ${student.course_count} course(s). This cannot be undone.`,
      )
    )
      return;
    begin(student.id);
    try {
      await api<void>(`/teacher/students/${student.id}`, { method: "DELETE" });
      setSuccess(`${student.display_name} was removed.`);
      setRefresh((n) => n + 1);
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy("");
    }
  }
  const full = !!data && data.used >= data.limit;
  return (
    <>
      <div className="page-heading">
        <p className="eyebrow">Your class</p>
        <h1>Students</h1>
        <p className="muted">
          Create student accounts, then add students to courses from each course
          page.
        </p>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {success && (
        <p className="notice" role="status">
          {success}
        </p>
      )}
      <div className="dashboard-grid">
        <section aria-labelledby="students-heading">
          <div className="section-heading">
            <h2 id="students-heading">Your students</h2>
            {data && (
              <span className={`count${full ? " count-full" : ""}`}>
                {data.used} of {data.limit} students used
              </span>
            )}
          </div>
          {loading ? (
            <p role="status">Loading students…</p>
          ) : !data ? null : data.students.length === 0 ? (
            <div className="empty-state">
              <span className="empty-mark" aria-hidden="true">
                ＋
              </span>
              <h3>No students yet</h3>
              <p>Add a student to give them a login for your courses.</p>
            </div>
          ) : (
            <ul className="document-list">
              {data.students.map((s) => (
                <li key={s.id} className="document-card">
                  <div className="file-icon" aria-hidden="true">
                    {s.display_name.slice(0, 2).toUpperCase()}
                  </div>
                  <div className="document-info">
                    <h3>{s.display_name}</h3>
                    <p>{s.email}</p>
                    <span className="status">
                      {s.course_count} course{s.course_count === 1 ? "" : "s"} ·{" "}
                      {s.must_change_password
                        ? "Has not set a password yet"
                        : `Last login ${formatDateTime(s.last_login_at)}`}
                    </span>
                  </div>
                  <div className="document-actions">
                    <button
                      className="text-button danger"
                      disabled={!!busy}
                      onClick={() => void remove(s)}
                    >
                      Remove
                      <span className="sr-only"> {s.display_name}</span>
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="panel create-panel">
          <p className="eyebrow">New student</p>
          <h2>Add a student</h2>
          <p className="muted">
            Boardom generates a temporary password. The student must change it
            at first login.
          </p>
          {created && (
            <TempPassword
              name={created.student.display_name}
              email={created.student.email}
              password={created.temporary_password}
              onDismiss={() => setCreated(null)}
            />
          )}
          {full && (
            <p className="notice" role="status">
              Student limit reached ({data?.used} of {data?.limit}). Remove a
              student or ask the admin to raise your limit.
            </p>
          )}
          <form onSubmit={add}>
            <fieldset disabled={!!busy || full || !data}>
              <label>
                Name
                <input
                  name="display_name"
                  required
                  maxLength={100}
                  placeholder="Sam Rivera"
                />
              </label>
              <label>
                Email address
                <input
                  name="email"
                  type="email"
                  required
                  maxLength={254}
                  placeholder="student@school.edu"
                />
              </label>
              <button type="submit">
                {busy === "create" ? "Creating…" : "Add student"}
              </button>
            </fieldset>
          </form>
        </section>
      </div>
    </>
  );
}
export default function StudentsPage() {
  return (
    <Protected roles={["teacher"]}>
      <StudentsView />
    </Protected>
  );
}
