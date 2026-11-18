"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Protected, useAuth, useRequestError } from "@/components/AuthProvider";
import { api, formatDate, type Workspace } from "@/lib/api";

function Dashboard() {
  const { user } = useAuth();
  const handleError = useRequestError();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    api<Workspace[]>("/workspaces")
      .then((data) => {
        if (active) {
          setWorkspaces(data);
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
  }, [handleError, retry]);
  return (
    <>
      <div className="page-heading">
        <p className="eyebrow">Your teaching desk</p>
        <h1>Hello, {user?.display_name}.</h1>
        <p className="muted">
          A home for everything that goes into a good lesson.
        </p>
      </div>
      <div className="dashboard-grid">
        <section aria-labelledby="workspace-list">
          <div className="section-heading">
            <h2 id="workspace-list">Your workspaces</h2>
            <span className="count">{workspaces.length}</span>
          </div>
          {loading ? (
            <p role="status">Loading workspaces…</p>
          ) : error ? (
            <div className="panel">
              <p className="error" role="alert">
                {error}
              </p>
              <button
                onClick={() => {
                  setLoading(true);
                  setRetry(retry + 1);
                }}
              >
                Retry
              </button>
            </div>
          ) : workspaces.length === 0 ? (
            <div className="empty-state">
              <span className="empty-mark" aria-hidden="true">
                ＋
              </span>
              <h3>Your next lesson starts here</h3>
              <p>
                Create your first workspace, then bring in your teaching
                materials.
              </p>
            </div>
          ) : (
            <div className="workspace-list">
              {workspaces.map((w) => (
                <Link
                  className="workspace-card"
                  key={w.id}
                  href={`/workspaces/${w.id}`}
                >
                  <div>
                    <span className="tag">
                      {w.subject || "Lesson workspace"}
                    </span>
                    <h3>{w.title}</h3>
                    <p>
                      {w.learner_level} <span aria-hidden="true">·</span>{" "}
                      {w.lesson_duration_minutes} min
                    </p>
                    <small>Updated {formatDate(w.updated_at)}</small>
                  </div>
                  <span aria-hidden="true" className="card-arrow">
                    ↗
                  </span>
                </Link>
              ))}
            </div>
          )}
        </section>
        <section className="panel create-panel">
          <p className="eyebrow">Start something new</p>
          <h2>Create a course</h2>
          <p className="muted">
            A four-step setup: basics, audience and schedule, theory or lab, and
            topics and assessment. The syllabus generator follows it.
          </p>
          <Link className="button full-width" href="/workspaces/new">
            Set up a new course <span aria-hidden="true">→</span>
          </Link>
        </section>
      </div>
    </>
  );
}
export default function DashboardPage() {
  return (
    <Protected roles={["teacher"]}>
      <Dashboard />
    </Protected>
  );
}
