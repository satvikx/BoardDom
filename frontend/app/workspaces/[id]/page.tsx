"use client";
import { use, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Protected, useRequestError } from "@/components/AuthProvider";
import { WorkspaceForm } from "@/components/WorkspaceForm";
import {
  api,
  downloadDocument,
  formatDate,
  formatSize,
  type Workspace,
  type WorkspaceInput,
  type SourceDocument,
} from "@/lib/api";

function WorkspaceView({ id }: { id: string }) {
  const router = useRouter();
  const handleError = useRequestError();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [limit, setLimit] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [editing, setEditing] = useState(false);
  const [retry, setRetry] = useState(0);
  const base = `/workspaces/${id}`;
  useEffect(() => {
    let active = true;
    Promise.all([
      api<Workspace>(base),
      api<SourceDocument[]>(`${base}/documents`),
      api<{ max_upload_bytes: number }>("/config"),
    ])
      .then(([w, docs, config]) => {
        if (active) {
          setWorkspace(w);
          setDocuments(docs);
          setLimit(config.max_upload_bytes);
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
  }, [base, handleError, retry]);
  function begin(action: string) {
    setBusy(action);
    setError("");
    setSuccess("");
  }
  async function save(value: WorkspaceInput) {
    begin("save");
    try {
      setWorkspace(
        await api<Workspace>(base, {
          method: "PATCH",
          body: JSON.stringify(value),
        }),
      );
      setEditing(false);
      setSuccess("Workspace details saved.");
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy("");
    }
  }
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const file = data.get("file");
    if (file instanceof File && limit !== null && file.size > limit) {
      setSuccess("");
      setError(`Choose a file smaller than ${formatSize(limit)}.`);
      return;
    }
    begin("upload");
    try {
      const document = await api<SourceDocument>(`${base}/documents`, {
        method: "POST",
        body: data,
      });
      setDocuments((current) => [document, ...current]);
      form.reset();
      setSuccess(
        "Saved successfully. Open the source to extract and review its text.",
      );
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy("");
    }
  }
  async function removeDocument(document: SourceDocument) {
    if (
      !window.confirm(
        `Delete “${document.original_filename}”? This removes the stored file.`,
      )
    )
      return;
    begin(document.id);
    try {
      await api<void>(`${base}/documents/${document.id}`, { method: "DELETE" });
      setDocuments((current) => current.filter((d) => d.id !== document.id));
      setSuccess("Document deleted.");
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy("");
    }
  }
  async function download(document: SourceDocument) {
    begin(document.id);
    try {
      await downloadDocument(id, document);
      setSuccess("Download started.");
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy("");
    }
  }
  async function removeWorkspace() {
    if (
      !window.confirm(
        "Delete this workspace and all its source files? This cannot be undone.",
      )
    )
      return;
    begin("delete");
    try {
      await api<void>(base, { method: "DELETE" });
      router.push("/dashboard");
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy("");
    }
  }
  if (loading)
    return (
      <p className="loading" role="status">
        Loading your lesson…
      </p>
    );
  return (
    <>
      <Link className="back-link" href="/dashboard">
        ← All workspaces
      </Link>
      {error && (
        <div className="error" role="alert">
          {error}
          {!workspace && (
            <button
              className="secondary"
              onClick={() => {
                setLoading(true);
                setRetry(retry + 1);
              }}
            >
              Retry
            </button>
          )}
        </div>
      )}
      {success && (
        <p className="notice" role="status">
          {success}
        </p>
      )}
      {workspace && (
        <>
          <div className="page-heading workspace-heading">
            <p className="eyebrow">Lesson workspace</p>
            <h1>{workspace.title}</h1>
            <div className="metadata">
              <span className="tag">
                {workspace.subject || "No subject set"}
              </span>
              <span className="capitalize">{workspace.learner_level}</span>
              <span>{workspace.lesson_duration_minutes} minutes</span>
            </div>
            {workspace.description && (
              <p className="description">{workspace.description}</p>
            )}
          </div>
          <div className="workspace-grid">
            <section aria-labelledby="sources-heading">
              <div className="section-heading">
                <h2 id="sources-heading">Source materials</h2>
                <span className="count">{documents.length}</span>
              </div>
              <div className="panel upload-panel">
                <h3>Bring your lesson materials</h3>
                <p className="muted" id="upload-help">
                  PDF, Markdown (.md), or text (.txt). Up to{" "}
                  {limit === null ? "…" : formatSize(limit)} per file. Text
                  files must use UTF-8.
                </p>
                <form onSubmit={upload}>
                  <fieldset disabled={!!busy}>
                    <label className="file-label" htmlFor="source-file">
                      Choose a source file
                    </label>
                    <input
                      id="source-file"
                      type="file"
                      name="file"
                      accept=".pdf,.md,.txt"
                      required
                      aria-describedby="upload-help"
                    />
                    <button type="submit">
                      {busy === "upload" ? "Uploading…" : "Upload file"}
                    </button>
                  </fieldset>
                </form>
              </div>
              {documents.length === 0 ? (
                <div className="empty-state compact">
                  <h3>A clean slate</h3>
                  <p>Your uploaded sources will appear here.</p>
                </div>
              ) : (
                <ul className="document-list">
                  {documents.map((doc) => (
                    <li key={doc.id} className="document-card">
                      <div className="file-icon" aria-hidden="true">
                        {doc.original_filename.split(".").pop()?.toUpperCase()}
                      </div>
                      <div className="document-info">
                        <h3>{doc.original_filename}</h3>
                        <p>
                          {formatSize(doc.size_bytes)} ·{" "}
                          {formatDate(doc.created_at)}
                        </p>
                        <span className="status">
                          {doc.extraction_status.replace("_", " ")} ·{" "}
                          {doc.reviewed_at ? "Reviewed" : "Unreviewed"}
                        </span>
                        <p>
                          <Link href={`/workspaces/${id}/documents/${doc.id}`}>
                            {doc.extraction_status === "extracted"
                              ? "Review text"
                              : "Extract text / status"}
                          </Link>
                        </p>
                      </div>
                      <div className="document-actions">
                        <button
                          className="text-button"
                          disabled={!!busy}
                          onClick={() => void download(doc)}
                        >
                          Download
                          <span className="sr-only">
                            {" "}
                            {doc.original_filename}
                          </span>
                        </button>
                        <button
                          className="text-button danger"
                          disabled={!!busy}
                          onClick={() => void removeDocument(doc)}
                        >
                          Delete
                          <span className="sr-only">
                            {" "}
                            {doc.original_filename}
                          </span>
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <aside>
              <section className="panel">
                <div className="section-heading">
                  <h2>Lesson details</h2>
                  <button
                    className="text-button"
                    disabled={!!busy}
                    onClick={() => setEditing(!editing)}
                  >
                    {editing ? "Cancel" : "Edit"}
                  </button>
                </div>
                {editing ? (
                  <WorkspaceForm
                    initial={workspace}
                    busy={!!busy}
                    onSave={save}
                    submitLabel="Save changes"
                  />
                ) : (
                  <dl className="detail-list">
                    <div>
                      <dt>Subject</dt>
                      <dd>{workspace.subject || "Not set"}</dd>
                    </div>
                    <div>
                      <dt>Learner level</dt>
                      <dd className="capitalize">{workspace.learner_level}</dd>
                    </div>
                    <div>
                      <dt>Duration</dt>
                      <dd>{workspace.lesson_duration_minutes} minutes</dd>
                    </div>
                    <div>
                      <dt>Created</dt>
                      <dd>{formatDate(workspace.created_at)}</dd>
                    </div>
                  </dl>
                )}
              </section>
              <section className="delete-zone">
                <h3>Delete workspace</h3>
                <p>
                  This permanently removes the workspace and all its source
                  files.
                </p>
                <button
                  className="secondary danger"
                  disabled={!!busy}
                  onClick={() => void removeWorkspace()}
                >
                  {busy === "delete" ? "Deleting…" : "Delete workspace"}
                </button>
              </section>
            </aside>
          </div>
        </>
      )}
    </>
  );
}
export default function WorkspacePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <Protected>
      <WorkspaceView id={id} />
    </Protected>
  );
}
