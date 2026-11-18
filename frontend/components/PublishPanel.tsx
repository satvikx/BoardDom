"use client";
import { useEffect, useState } from "react";
import { useRequestError } from "./AuthProvider";
import { api, downloadFile, formatDateTime, type Publication } from "@/lib/api";

export function PublishPanel({
  base,
  refresh,
}: {
  base: string;
  refresh: number;
}) {
  const handleError = useRequestError();
  const [publication, setPublication] = useState<Publication | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    api<Publication>(`${base}/publication`)
      .then((data) => {
        if (active) setPublication(data);
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [base, refresh, handleError]);
  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy(false);
    }
  }
  const published = !!publication?.published_at;
  return (
    <section className="panel publish-panel" aria-labelledby="publish-heading">
      <div className="section-heading">
        <h2 id="publish-heading">Publish to students</h2>
        <span className={published ? "count" : "count count-draft"}>
          {published
            ? `Published ${formatDateTime(publication!.published_at)}`
            : "Not published"}
        </span>
      </div>
      <p className="muted">
        Students of yours see published unit notes and lab manuals, exactly as
        they were when you last published.
      </p>
      {publication?.unpublished_changes && published && (
        <p className="notice" role="status">
          You have changes students do not see yet. Publish again to update
          them.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <div className="button-row">
        <button
          disabled={busy}
          onClick={() =>
            void act(async () => {
              setPublication(
                await api<Publication>(`${base}/publish`, { method: "POST" }),
              );
              setNotice("Published. Students can now see this course.");
            })
          }
        >
          {published ? "Publish changes" : "Publish course"}
        </button>
        {published && (
          <button
            className="secondary"
            disabled={busy}
            onClick={() =>
              void act(async () => {
                if (!window.confirm("Hide this course from students?")) return;
                setPublication(
                  await api<Publication>(`${base}/unpublish`, {
                    method: "POST",
                  }),
                );
                setNotice("Unpublished. Students no longer see this course.");
              })
            }
          >
            Unpublish
          </button>
        )}
        <button
          className="secondary"
          disabled={busy}
          onClick={() =>
            void act(() =>
              downloadFile(`${base}/export?format=pdf`, "notes.pdf"),
            )
          }
        >
          Export notes (PDF)
        </button>
        <button
          className="secondary"
          disabled={busy}
          onClick={() =>
            void act(() => downloadFile(`${base}/export?format=md`, "notes.md"))
          }
        >
          Export notes (Markdown)
        </button>
      </div>
    </section>
  );
}
