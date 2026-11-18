"use client";
import { useEffect, useState } from "react";
import { useRequestError } from "./AuthProvider";
import { api, type Finding, type Job } from "@/lib/api";

export function ResearchPanel({
  base,
  disabled,
  refresh,
  onRun,
}: {
  base: string;
  disabled: boolean;
  refresh: number;
  onRun: () => void;
}) {
  const handleError = useRequestError();
  const [findings, setFindings] = useState<Finding[]>([]);
  const [lastRun, setLastRun] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let active = true;
    Promise.all([
      api<Finding[]>(`${base}/research`),
      api<Job[]>(`${base}/jobs?limit=20`),
    ])
      .then(([rows, jobs]) => {
        if (!active) return;
        setFindings(rows);
        setLastRun(jobs.find((j) => j.kind === "research") ?? null);
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [base, refresh, tick, handleError]);
  async function review(finding: Finding, status: Finding["status"]) {
    setError("");
    try {
      await api<Finding>(`${base}/research/${finding.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setTick((t) => t + 1);
    } catch (e) {
      setError(handleError(e));
    }
  }
  const unavailable = lastRun?.message?.startsWith("Web search is unavailable");
  const accepted = findings.filter((f) => f.status === "accepted").length;
  return (
    <section className="panel notes-panel" aria-labelledby="research-heading">
      <div className="section-heading">
        <h2 id="research-heading">Research findings</h2>
        <span className="count">{accepted} accepted</span>
      </div>
      <p className="muted">
        A web search on trusted educational sites. Accepted findings are cited
        as [W1], [W2]… when you (re)generate the syllabus. Results that look
        like prompt injection are set aside automatically.
      </p>
      {unavailable && (
        <p className="notice" role="status">
          Web research was unavailable last time, so it was skipped:{" "}
          {lastRun?.message}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="button-row">
        <button disabled={disabled} onClick={onRun}>
          {findings.length ? "Search again" : "Run web research"}
        </button>
      </div>
      {findings.length > 0 && (
        <ul className="document-list">
          {findings.map((f) => (
            <li key={f.id} className="document-card">
              <div className="file-icon" aria-hidden="true">
                {f.label}
              </div>
              <div className="document-info">
                <h3>
                  <a href={f.url} target="_blank" rel="noopener noreferrer">
                    {f.title}
                  </a>
                </h3>
                <p>{f.summary.slice(0, 280)}</p>
                <span
                  className={f.flagged ? "status status-flagged" : "status"}
                >
                  {f.flagged ? f.flag_reason : f.status} · search “{f.query}”
                </span>
              </div>
              <div className="document-actions">
                {!f.flagged && f.status !== "accepted" && (
                  <button
                    className="text-button"
                    onClick={() => void review(f, "accepted")}
                  >
                    Accept
                  </button>
                )}
                {!f.flagged && f.status !== "ignored" && (
                  <button
                    className="text-button danger"
                    onClick={() => void review(f, "ignored")}
                  >
                    Ignore
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
