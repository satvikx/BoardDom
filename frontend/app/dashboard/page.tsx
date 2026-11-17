"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Protected, useAuth, useRequestError } from "@/components/AuthProvider";
import { WorkspaceForm } from "@/components/WorkspaceForm";
import {
  api,
  formatDate,
  type Workspace,
  type WorkspaceInput,
} from "@/lib/api";

function Dashboard() {
  const { user } = useAuth();
  const router = useRouter();
  const handleError = useRequestError();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createError, setCreateError] = useState("");
  const [busy, setBusy] = useState(false);
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
  async function create(value: WorkspaceInput) {
    setBusy(true);
    setCreateError("");
    try {
      const workspace = await api<Workspace>("/workspaces", {
        method: "POST",
        body: JSON.stringify(value),
      });
      router.push(`/workspaces/${workspace.id}`);
    } catch (e) {
      setCreateError(handleError(e));
    } finally {
      setBusy(false);
    }
  }
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
          <h2>Create a workspace</h2>
          <p className="muted">A few details to set the scene.</p>
          {createError && (
            <p className="error" role="alert">
              {createError}
            </p>
          )}
          <WorkspaceForm
            busy={busy}
            onSave={create}
            submitLabel="Create workspace"
          />
        </section>
      </div>
    </>
  );
}
export default function DashboardPage() {
  return (
    <Protected>
      <Dashboard />
    </Protected>
  );
}
