"use client";
import { use, useCallback, useEffect, useState } from "react";
import { Protected, useRequestError } from "@/components/AuthProvider";
import { api, downloadDocument, type SourceDocument } from "@/lib/api";

type Unit = {
  id: string;
  label: string;
  original_text: string;
  corrected_text: string | null;
  effective_text: string;
  revision: number;
};
type Content = { document: SourceDocument; units: Unit[] };
function Editor({ id, documentId }: { id: string; documentId: string }) {
  const base = `/workspaces/${id}/documents/${documentId}`;
  const handleError = useRequestError();
  const [content, setContent] = useState<Content | null>(null);
  const [selected, setSelected] = useState(0);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const unit = content?.units[selected];
  const dirty = !!unit && draft !== unit.effective_text;
  const load = useCallback(
    () =>
      api<Content>(`${base}/content`)
        .then((value) => {
          setContent(value);
          setSelected(0);
          setDraft(value.units[0]?.effective_text ?? "");
          setError("");
        })
        .catch((e) => setError(handleError(e))),
    [base, handleError],
  );
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (content?.document.extraction_status !== "processing") return;
    let active = true;
    const timer = setTimeout(() => {
      api<Content>(`${base}/content`)
        .then((value) => {
          if (active) {
            setContent(value);
            setDraft(value.units[0]?.effective_text ?? "");
          }
        })
        .catch((e) => {
          if (active) setError(handleError(e));
        });
    }, 1500);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [content, base, handleError]);
  useEffect(() => {
    if (!dirty) return;
    const before = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const click = (event: MouseEvent) => {
      const target = event.target as Element;
      if (
        target.closest("a, header button") &&
        !window.confirm("Leave without saving your changes?")
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", before);
    document.addEventListener("click", click, true);
    return () => {
      window.removeEventListener("beforeunload", before);
      document.removeEventListener("click", click, true);
    };
  }, [dirty]);
  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy(false);
    }
  }
  async function save(reset = false) {
    if (!unit) return;
    await act(async () => {
      const updated = await api<Unit>(`${base}/units/${unit.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          corrected_text: reset ? null : draft,
          expected_revision: unit.revision,
        }),
      });
      // Refresh metadata after a successful save, retaining the selected unit.
      const next = await api<Content>(`${base}/content`);
      setContent(next);
      setDraft(updated.effective_text);
      setMessage("Source text saved.");
    });
  }
  if (!content)
    return (
      <section className="panel">
        <p role={error ? "alert" : "status"}>{error || "Loading source…"}</p>
        {error && <button onClick={() => void load()}>Retry</button>}
      </section>
    );
  const doc = content.document;
  return (
    <>
      <a className="back-link" href={`/workspaces/${id}`}>
        ← Workspace
      </a>
      <div className="page-heading">
        <h1>{doc.original_filename}</h1>
        <p>
          {doc.extraction_status.replace("_", " ")} ·{" "}
          {doc.reviewed_at ? "Reviewed" : "Unreviewed"}
        </p>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
          <p>
            Your local draft is retained. Copy it before reloading if you want
            to compare.
          </p>
          <button
            disabled={busy}
            onClick={() => {
              if (
                !dirty ||
                window.confirm(
                  "Reload latest content and discard your local draft?",
                )
              )
                void load();
            }}
          >
            Reload latest content
          </button>
        </div>
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {doc.extraction_error_message && (
        <p className="error" role="alert">
          {doc.extraction_error_message}
        </p>
      )}
      {doc.extraction_warnings.map((warning, i) => (
        <p key={i} className="notice">
          {warning}
        </p>
      ))}
      <div className="hero-actions">
        <button
          disabled={busy}
          onClick={() => void act(() => downloadDocument(id, doc))}
        >
          Download original
        </button>
        {["uploaded", "failed", "needs_ocr"].includes(
          doc.extraction_status,
        ) && (
          <button
            disabled={busy}
            onClick={() =>
              void act(async () => {
                const next = await api<SourceDocument>(`${base}/extract`, {
                  method: "POST",
                });
                setContent({ ...content, document: next });
              })
            }
          >
            {doc.extraction_status === "uploaded"
              ? "Extract text"
              : "Retry extraction"}
          </button>
        )}
        {doc.extraction_status === "processing" && (
          <p role="status">Extracting text… This may take up to a minute.</p>
        )}
      </div>
      {unit && (
        <section className="panel" style={{ marginTop: 24 }}>
          <label>
            Page or source unit
            <select
              value={selected}
              onChange={(e) => {
                if (
                  dirty &&
                  !window.confirm("Discard unsaved changes on this page?")
                )
                  return;
                const index = Number(e.target.value);
                setSelected(index);
                setDraft(content.units[index].effective_text);
              }}
            >
              {content.units.map((u, i) => (
                <option key={u.id} value={i}>
                  {u.label}
                  {!u.effective_text.trim() ? " — no usable text" : ""}
                </option>
              ))}
            </select>
          </label>
          <label>
            Editable source text
            <textarea
              rows={18}
              value={draft}
              disabled={busy || doc.extraction_status !== "extracted"}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <div className="hero-actions">
            <button
              disabled={busy || !dirty || doc.extraction_status !== "extracted"}
              onClick={() => void save()}
            >
              Save text
            </button>
            <button
              className="secondary"
              disabled={busy || doc.extraction_status !== "extracted"}
              onClick={() => {
                if (
                  window.confirm(
                    "Reset this unit to its original extracted text?",
                  )
                )
                  void save(true);
              }}
            >
              Reset to original
            </button>
          </div>
          <details style={{ marginTop: 20 }}>
            <summary>Original extracted text (read only)</summary>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {unit.original_text || "No text extracted from this unit."}
            </pre>
          </details>
        </section>
      )}
      {doc.extraction_status === "extracted" && (
        <section className="panel" style={{ marginTop: 24 }}>
          <p>
            Compare the text with the original file before marking it reviewed.
            Save all edits first. To replace this source, delete it and upload a
            new file.
          </p>
          <div className="hero-actions">
            <button
              disabled={busy || dirty}
              onClick={() =>
                void act(async () => {
                  const next = await api<SourceDocument>(`${base}/review`, {
                    method: "PATCH",
                    body: JSON.stringify({
                      reviewed: !doc.reviewed_at,
                      expected_content_revision: doc.content_revision,
                    }),
                  });
                  setContent({ ...content, document: next });
                  setMessage(
                    next.reviewed_at
                      ? "Source marked reviewed."
                      : "Review reopened.",
                  );
                })
              }
            >
              {doc.reviewed_at ? "Reopen review" : "Mark reviewed"}
            </button>
            <button
              disabled={busy || dirty}
              onClick={() => void act(() => downloadDocument(id, doc, true))}
            >
              Download corrected text
            </button>
          </div>
        </section>
      )}
    </>
  );
}
export default function Page({
  params,
}: {
  params: Promise<{ id: string; documentId: string }>;
}) {
  const values = use(params);
  return (
    <Protected roles={["teacher"]}>
      <Editor {...values} />
    </Protected>
  );
}
