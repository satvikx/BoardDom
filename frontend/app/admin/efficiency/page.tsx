"use client";
import { useEffect, useState } from "react";
import { Protected, useRequestError } from "@/components/AuthProvider";
import { api } from "@/lib/api";

type Summary = {
  calls: number;
  input_tokens: number;
  cached_tokens: number;
  output_tokens: number;
  cache_hit_rate: number | null;
  avg_latency_ms: number | null;
  cost_usd: number | null;
};
type Report = {
  totals: Summary;
  by_purpose: (Summary & { purpose: string })[];
  by_course: (Summary & {
    workspace_id: string;
    title: string;
    generation_calls: number;
    naive_input_tokens: number;
    pipeline_input_tokens: number;
  })[];
  by_pipeline: Record<string, Summary>;
  per_generated_course: {
    courses: number;
    avg_tokens: number;
    avg_cost_usd: number | null;
  } | null;
  naive_vs_pipeline: {
    naive_input_tokens: number;
    pipeline_input_tokens: number;
    saving: number | null;
  };
  token_unit: string;
  prices_known_for: string[];
};

const n = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : v.toLocaleString();
const usd = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : `$${v.toFixed(4)}`;
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`;

function Columns({ s }: { s: Summary }) {
  return (
    <>
      <td>{n(s.calls)}</td>
      <td>{n(s.input_tokens)}</td>
      <td>{n(s.cached_tokens)}</td>
      <td>{n(s.output_tokens)}</td>
      <td>{n(s.avg_latency_ms)}</td>
      <td>{usd(s.cost_usd)}</td>
    </>
  );
}

const HEAD = ["Calls", "Input", "Cached", "Output", "Avg ms", "Cost"];

function Efficiency() {
  const handleError = useRequestError();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api<Report>("/admin/efficiency")
      .then((data) => {
        if (active) setReport(data);
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [handleError]);
  if (!report)
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : (
      <p className="loading" role="status">
        Loading…
      </p>
    );
  const t = report.totals;
  const cmp = report.naive_vs_pipeline;
  return (
    <>
      <div className="page-heading">
        <p className="eyebrow">Administration</p>
        <h1>Efficiency</h1>
        <p className="muted">
          From every recorded AI call (prompts are never stored). Units:{" "}
          {report.token_unit}. Costs need prices for the model (known:{" "}
          {report.prices_known_for.join(", ") || "none"}).
        </p>
      </div>
      <div className="stat-grid">
        <div className="stat">
          <span>AI calls</span>
          <strong>{n(t.calls)}</strong>
        </div>
        <div className="stat">
          <span>Input / output</span>
          <strong>
            {n(t.input_tokens)} / {n(t.output_tokens)}
          </strong>
        </div>
        <div className="stat">
          <span>Cache hit rate</span>
          <strong>{pct(t.cache_hit_rate)}</strong>
        </div>
        <div className="stat">
          <span>Avg latency</span>
          <strong>{n(t.avg_latency_ms)} ms</strong>
        </div>
        <div className="stat">
          <span>Total cost</span>
          <strong>{usd(t.cost_usd)}</strong>
        </div>
        <div className="stat">
          <span>Per generated course</span>
          <strong>
            {report.per_generated_course
              ? `${n(report.per_generated_course.avg_tokens)} · ${usd(report.per_generated_course.avg_cost_usd)}`
              : "n/a"}
          </strong>
        </div>
      </div>
      <section className="panel">
        <h2>Naive versus our pipeline</h2>
        <p className="muted">
          Estimate: a naive pipeline sends each course&apos;s whole source text
          with every generation call; ours sends only the retrieved passages.
          The Evals page measures the same comparison on a golden course.
        </p>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Pipeline</th>
                <th scope="col">Input for generation</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Naive (whole sources)</td>
                <td>{n(cmp.naive_input_tokens)}</td>
              </tr>
              <tr>
                <td>Boardom (retrieval)</td>
                <td>
                  <strong>{n(cmp.pipeline_input_tokens)}</strong>{" "}
                  {cmp.saving !== null && `(saves ${pct(cmp.saving)})`}
                </td>
              </tr>
              {Object.entries(report.by_pipeline).map(([name, s]) => (
                <tr key={name}>
                  <td>Measured, {name} pipeline (all calls)</td>
                  <td>
                    {n(s.input_tokens + s.output_tokens)} over {s.calls} calls
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <h2 className="subheading">Per course</h2>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Course</th>
              {HEAD.map((h) => (
                <th key={h} scope="col">
                  {h}
                </th>
              ))}
              <th scope="col">Naive est.</th>
            </tr>
          </thead>
          <tbody>
            {report.by_course.map((c) => (
              <tr key={c.workspace_id}>
                <td>{c.title}</td>
                <Columns s={c} />
                <td>{n(c.naive_input_tokens)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2 className="subheading">Per artifact / purpose</h2>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Purpose</th>
              {HEAD.map((h) => (
                <th key={h} scope="col">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {report.by_purpose.map((p) => (
              <tr key={p.purpose}>
                <td>{p.purpose.replace(/_/g, " ")}</td>
                <Columns s={p} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function EfficiencyPage() {
  return (
    <Protected roles={["admin"]}>
      <Efficiency />
    </Protected>
  );
}
