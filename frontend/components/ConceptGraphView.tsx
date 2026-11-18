"use client";
import { useEffect, useState } from "react";
import { useRequestError } from "./AuthProvider";
import { api, type ConceptGraph } from "@/lib/api";

// Layered view: column N holds concepts whose longest prerequisite chain has length N.
export function ConceptGraphView({
  base,
  disabled,
  refresh,
  onBuild,
}: {
  base: string;
  disabled: boolean;
  refresh: number;
  onBuild: () => void;
}) {
  const handleError = useRequestError();
  const [graph, setGraph] = useState<ConceptGraph | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api<ConceptGraph>(`${base}/concepts`)
      .then((data) => {
        if (active) setGraph(data);
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [base, refresh, handleError]);
  const names = new Map(graph?.concepts.map((c) => [c.id, c.name]));
  const levels: ConceptGraph["concepts"][] = [];
  for (const c of graph?.concepts ?? []) (levels[c.level] ??= []).push(c);
  return (
    <section className="panel notes-panel" aria-labelledby="concepts-heading">
      <div className="section-heading">
        <h2 id="concepts-heading">Concept graph</h2>
        <span className="count">
          {graph
            ? `${graph.concepts.length} concepts · ${graph.edge_count} links`
            : "…"}
        </span>
      </div>
      <p className="muted">
        Concepts from the syllabus and notes, ordered by their prerequisites.
        The exam-prep coach uses it to find gaps.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="button-row">
        <button disabled={disabled} onClick={onBuild}>
          {graph?.concepts.length ? "Rebuild graph" : "Build graph"}
        </button>
      </div>
      {graph && graph.concepts.length > 0 && (
        <div className="graph-levels">
          {levels.map((column, level) => (
            <div className="graph-level" key={level}>
              <p className="eyebrow">
                {level === 0 ? "Foundations" : `Step ${level + 1}`}
              </p>
              {(column ?? []).map((c) => (
                <article className="concept-card" key={c.id}>
                  <h3>{c.name}</h3>
                  {c.description && <p>{c.description}</p>}
                  {c.prerequisite_ids.length > 0 && (
                    <small>
                      Needs:{" "}
                      {c.prerequisite_ids.map((id) => names.get(id)).join(", ")}
                    </small>
                  )}
                  {c.unit_title && (
                    <small className="cell-sub">{c.unit_title}</small>
                  )}
                </article>
              ))}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
