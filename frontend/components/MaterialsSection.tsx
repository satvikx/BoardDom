"use client";
import { useEffect, useState } from "react";
import { useRequestError } from "./AuthProvider";
import { NotesPanel } from "./NotesPanel";
import {
  api,
  formatDateTime,
  type ArtifactKind,
  type NotesSummary,
} from "@/lib/api";

const TABS: { kind: ArtifactKind; label: string; lab?: boolean }[] = [
  { kind: "unit_notes", label: "Unit notes" },
  { kind: "lab_manual", label: "Lab manuals", lab: true },
  { kind: "lesson_plan", label: "Lesson plans" },
  { kind: "rubric", label: "Rubric" },
];

export function MaterialsSection({
  base,
  hasLab,
  disabled,
  refresh,
  onGenerate,
}: {
  base: string;
  hasLab: boolean;
  disabled: boolean;
  refresh: number;
  onGenerate: (kind: ArtifactKind, unitIds?: string[]) => void;
}) {
  const handleError = useRequestError();
  const [kind, setKind] = useState<ArtifactKind>("unit_notes");
  const [rows, setRows] = useState<NotesSummary[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let active = true;
    api<NotesSummary[]>(`${base}/artifacts?kind=${kind}`)
      .then((data) => {
        if (active) {
          setRows(data);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [base, kind, refresh, tick, handleError]);
  const tabs = TABS.filter((t) => !t.lab || hasLab);
  const label = TABS.find((t) => t.kind === kind)?.label ?? "";
  const missing = rows.filter((r) => !r.current_version);
  const perUnit = kind !== "rubric";
  return (
    <section className="notes-section" aria-labelledby="materials-heading">
      <div className="section-heading">
        <h2 id="materials-heading">Course materials</h2>
      </div>
      <div className="tabs" role="tablist" aria-label="Material type">
        {tabs.map((t) => (
          <button
            key={t.kind}
            role="tab"
            aria-selected={t.kind === kind}
            className={t.kind === kind ? "tab active" : "tab"}
            onClick={() => {
              setKind(t.kind);
              setOpen(null);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      {!hasLab && (
        <p className="muted small-print">
          Lab manuals appear when the course has a lab (edit the course
          details).
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="button-row">
        {perUnit && missing.length > 0 && (
          <button
            disabled={disabled}
            onClick={() =>
              onGenerate(
                kind,
                missing.map((r) => r.unit_id!),
              )
            }
          >
            Generate missing ({missing.length})
          </button>
        )}
        {perUnit && missing.length < rows.length && (
          <button
            className="secondary"
            disabled={disabled}
            onClick={() => {
              if (
                window.confirm(
                  `Regenerate every ${label.toLowerCase()} item? Each gets a new version; history is kept.`,
                )
              )
                onGenerate(kind);
            }}
          >
            Regenerate all
          </button>
        )}
      </div>
      <ul className="document-list">
        {rows.map((n) => (
          <li key={n.unit_id ?? "course"} className="document-card">
            <div className="file-icon" aria-hidden="true">
              {perUnit ? n.position + 1 : "★"}
            </div>
            <div className="document-info">
              <h3>{n.unit_title}</h3>
              <span className="status">
                {n.current_version
                  ? `Version ${n.current_version} · updated ${formatDateTime(n.updated_at)}`
                  : "Not generated"}
                {n.published_version
                  ? ` · published v${n.published_version}`
                  : ""}
                {n.warning_count > 0 &&
                  ` · ${n.warning_count} warning${n.warning_count === 1 ? "" : "s"}`}
              </span>
            </div>
            <div className="document-actions">
              {n.artifact_id && n.current_version > 0 && (
                <button
                  className="text-button"
                  onClick={() =>
                    setOpen(open === n.artifact_id ? null : n.artifact_id)
                  }
                >
                  {open === n.artifact_id ? "Close" : "Open"}
                </button>
              )}
              <button
                className="text-button"
                disabled={disabled}
                onClick={() =>
                  onGenerate(kind, n.unit_id ? [n.unit_id] : undefined)
                }
              >
                {n.current_version ? "Regenerate" : "Generate"}
              </button>
            </div>
          </li>
        ))}
      </ul>
      {open && (
        <NotesPanel
          key={`${open}-${rows.find((r) => r.artifact_id === open)?.current_version}`}
          base={base}
          artifactId={open}
          onChanged={() => setTick((t) => t + 1)}
        />
      )}
    </section>
  );
}
