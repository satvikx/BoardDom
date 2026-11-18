"use client";
import { useEffect, useState } from "react";
import { useRequestError } from "./AuthProvider";
import { Markdown } from "./Markdown";
import { api, formatDateTime, type Notes } from "@/lib/api";

export function NotesPanel({
  base,
  artifactId,
  onChanged,
}: {
  base: string;
  artifactId: string;
  onChanged: () => void;
}) {
  const handleError = useRequestError();
  const [notes, setNotes] = useState<Notes | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const url = `${base}/artifacts/${artifactId}`;
  useEffect(() => {
    let active = true;
    api<Notes>(viewing ? `${url}?number=${viewing}` : url)
      .then((data) => {
        if (active) {
          setNotes(data);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [url, viewing, handleError]);
  async function save() {
    if (!notes || draft === null) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const saved = await api<Notes>(url, {
        method: "PUT",
        body: JSON.stringify({
          markdown: draft,
          expected_version: notes.current_version,
        }),
      });
      setNotes(saved);
      setDraft(null);
      setSuccess(`Saved as version ${saved.number}.`);
      onChanged();
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy(false);
    }
  }
  async function restore(number: number) {
    if (!notes) return;
    if (!window.confirm(`Restore version ${number} as a new version?`)) return;
    setBusy(true);
    setError("");
    try {
      const saved = await api<Notes>(`${url}/restore/${number}`, {
        method: "POST",
        body: JSON.stringify({ expected_version: notes.current_version }),
      });
      setViewing(null);
      setNotes(saved);
      setSuccess(`Version ${number} restored as version ${saved.number}.`);
      onChanged();
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy(false);
    }
  }
  if (!notes)
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : (
      <p role="status" className="muted">
        Loading…
      </p>
    );
  const labels = Object.keys(notes.citations);
  const isOld = notes.number !== notes.current_version;
  return (
    <section className="panel notes-panel" aria-labelledby="notes-title">
      <div className="section-heading">
        <h2 id="notes-title">{notes.unit_title}</h2>
        <span className="count">
          Version {notes.number}
          {isOld ? ` of ${notes.current_version}` : ""} · {notes.origin}
        </span>
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
      {isOld && (
        <p className="notice" role="status">
          You are viewing an older version.{" "}
          <button
            className="text-button"
            disabled={busy}
            onClick={() => void restore(notes.number)}
          >
            Restore it
          </button>{" "}
          or{" "}
          <button className="text-button" onClick={() => setViewing(null)}>
            back to current
          </button>
          .
        </p>
      )}
      {notes.warnings.length > 0 && !isOld && (
        <ul className="warning-list">
          {notes.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {draft !== null ? (
        <>
          <label>
            Edit (markdown; cite sources as [C3])
            <textarea
              className="notes-editor"
              rows={20}
              value={draft}
              maxLength={200000}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <div className="button-row">
            <button
              disabled={busy || !draft.trim()}
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Save as new version"}
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => setDraft(null)}
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          {!isOld && (
            <div className="button-row">
              <button
                className="secondary"
                onClick={() => setDraft(notes.markdown)}
              >
                Edit
              </button>
            </div>
          )}
          <Markdown text={notes.markdown} citations={labels} />
        </>
      )}
      <h3 className="subheading">Sources cited</h3>
      {labels.length === 0 ? (
        <p className="muted">No citations.</p>
      ) : (
        <ol className="citation-list">
          {labels.map((label) => {
            const c = notes.citations[label];
            return (
              <li key={label} id={`cite-${label}`}>
                <strong>[{label}]</strong> {c.document}
                {c.page ? `, page ${c.page}` : ""}
                <small className="cell-sub">“{c.excerpt}”</small>
              </li>
            );
          })}
        </ol>
      )}
      <h3 className="subheading">Version history</h3>
      <ul className="version-list">
        {notes.versions.map((v) => (
          <li key={v.number}>
            <button
              className="text-button"
              disabled={v.number === notes.number}
              onClick={() =>
                setViewing(v.number === notes.current_version ? null : v.number)
              }
            >
              Version {v.number}
            </button>{" "}
            <span className="muted">
              {v.origin} · {formatDateTime(v.created_at)}
              {v.created_by_name ? ` · ${v.created_by_name}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
