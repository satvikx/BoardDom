"use client";
import { useEffect, useState } from "react";
import { Protected, useRequestError } from "@/components/AuthProvider";
import { api, formatDateTime } from "@/lib/api";

type Metric = {
  name: string;
  baseline: number | null;
  full: number | null;
  n: number;
  false_positive_rate?: { baseline: number | null; full: number | null };
};
type EvalRun = {
  id: string;
  status: "running" | "succeeded" | "failed";
  provider: string;
  message: string | null;
  started_at: string;
  finished_at: string | null;
  results: {
    metrics?: Metric[];
    tokens?: Record<string, number>;
    demo_mode?: boolean;
    seconds?: number;
  };
};

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`;

function Evals() {
  const handleError = useRequestError();
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let active = true;
    api<EvalRun[]>("/admin/evals")
      .then((data) => {
        if (active) setRuns(data);
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [tick, handleError]);
  const running = runs[0]?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(() => setTick((t) => t + 1), 1500);
    return () => clearTimeout(timer);
  }, [running, runs]);
  async function start() {
    setError("");
    try {
      await api<EvalRun>("/admin/evals", { method: "POST" });
      setTick((t) => t + 1);
    } catch (e) {
      setError(handleError(e));
    }
  }
  const latest = runs.find((r) => r.status === "succeeded");
  return (
    <>
      <div className="page-heading">
        <p className="eyebrow">Administration</p>
        <h1>Evals</h1>
        <p className="muted">
          A small golden course scored twice: a plain prompt (baseline) and
          Boardom&apos;s pipeline (retrieval, concept graph, validators,
          guardrails). Runs on a temporary database. The CLI does the same:{" "}
          <code>uv run python -m app.evals</code>.
        </p>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="button-row">
        <button disabled={running} onClick={() => void start()}>
          {running ? "Running…" : "Run evals"}
        </button>
      </div>
      {latest?.results.metrics && (
        <section className="panel">
          <div className="section-heading">
            <h2>Latest results</h2>
            <span className="count">
              {latest.provider}
              {latest.results.demo_mode ? " · demo mode" : ""} ·{" "}
              {formatDateTime(latest.finished_at)}
            </span>
          </div>
          {latest.results.demo_mode && (
            <p className="notice">
              Demo mode: the offline model shows what the pipeline&apos;s checks
              add, not real model quality. Add an AI key for real numbers.
            </p>
          )}
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Metric</th>
                  <th scope="col">Baseline</th>
                  <th scope="col">Full pipeline</th>
                  <th scope="col">Cases</th>
                </tr>
              </thead>
              <tbody>
                {latest.results.metrics.map((m) => (
                  <tr key={m.name}>
                    <td>
                      {m.name}
                      {m.false_positive_rate && (
                        <small className="cell-sub">
                          false positives: {pct(m.false_positive_rate.baseline)}{" "}
                          → {pct(m.false_positive_rate.full)}
                        </small>
                      )}
                    </td>
                    <td>{pct(m.baseline)}</td>
                    <td>
                      <strong>{pct(m.full)}</strong>
                    </td>
                    <td>{m.n}</td>
                  </tr>
                ))}
                {latest.results.tokens && (
                  <tr>
                    <td>Tokens used</td>
                    <td>{latest.results.tokens.baseline ?? 0}</td>
                    <td>{latest.results.tokens.full ?? 0}</td>
                    <td />
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <h2 className="subheading">History</h2>
      <ul className="version-list">
        {runs.map((r) => (
          <li key={r.id}>
            <strong>{r.status}</strong>{" "}
            <span className="muted">
              {r.provider} · {formatDateTime(r.started_at)}
              {r.results.seconds ? ` · ${r.results.seconds} s` : ""}
              {r.message ? ` · ${r.message}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

export default function EvalsPage() {
  return (
    <Protected roles={["admin"]}>
      <Evals />
    </Protected>
  );
}
