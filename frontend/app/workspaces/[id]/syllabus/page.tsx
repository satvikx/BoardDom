"use client";
import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Protected, useRequestError } from "@/components/AuthProvider";
import { ConceptGraphView } from "@/components/ConceptGraphView";
import { MaterialsSection } from "@/components/MaterialsSection";
import { PublishPanel } from "@/components/PublishPanel";
import { ResearchPanel } from "@/components/ResearchPanel";
import {
  api,
  formatDateTime,
  type Citation,
  type Job,
  type Syllabus,
  type Workspace,
} from "@/lib/api";

const JOB_LABELS: Record<string, string> = {
  syllabus: "Drafting syllabus",
  notes: "Generating notes",
  lab_manual: "Generating lab manuals",
  lesson_plan: "Planning lessons",
  rubric: "Writing the rubric",
  concepts: "Mapping concepts",
  research: "Researching the web",
};

type EditUnit = {
  id?: string;
  title: string;
  summary: string;
  topics: string;
  weeks: number | null;
  citations: Record<string, Citation>;
};

function toEdit(syllabus: Syllabus | null): EditUnit[] {
  return (syllabus?.units ?? []).map((u) => ({
    id: u.id,
    title: u.title,
    summary: u.summary,
    topics: u.topics.join("\n"),
    weeks: u.weeks,
    citations: u.citations ?? {},
  }));
}

function UnitMeta({
  weeks,
  citations,
}: {
  weeks: number | null;
  citations: Record<string, Citation>;
}) {
  const labels = Object.keys(citations);
  if (!weeks && !labels.length) return null;
  return (
    <p className="unit-meta">
      {weeks ? `${weeks} week${weeks === 1 ? "" : "s"}` : ""}
      {labels.map((label) => (
        <span
          key={label}
          className={label.startsWith("W") ? "cite cite-web" : "cite"}
          title={`${citations[label].document}: ${citations[label].excerpt}`}
        >
          {label}
        </span>
      ))}
    </p>
  );
}

function CourseContent({ id }: { id: string }) {
  const handleError = useRequestError();
  const base = `/workspaces/${id}`;
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [syllabus, setSyllabus] = useState<Syllabus | null>(null);
  const [units, setUnits] = useState<EditUnit[]>([]);
  const [dirty, setDirty] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchAll = useCallback(
    () =>
      Promise.all([
        api<Workspace>(base),
        api<Syllabus | null>(`${base}/syllabus`),
      ]),
    [base],
  );
  const apply = useCallback(([w, s]: [Workspace, Syllabus | null]) => {
    setWorkspace(w);
    setSyllabus(s);
    setUnits(toEdit(s));
    setDirty(false);
  }, []);
  const reload = useCallback(
    async () => apply(await fetchAll()),
    [apply, fetchAll],
  );

  const follow = useCallback(
    (started: Job) => {
      setJob(started);
      const tick = async () => {
        try {
          const current = await api<Job>(`${base}/jobs/${started.id}`);
          setJob(current);
          if (current.status === "queued" || current.status === "running") {
            timer.current = setTimeout(() => void tick(), 1500);
            return;
          }
          await reload();
          setRefresh((r) => r + 1);
          if (current.status === "succeeded")
            setSuccess(current.message ?? "Done.");
          else setError(current.message ?? "The job failed. Please retry.");
          setJob(null);
        } catch (e) {
          setError(handleError(e));
          setJob(null);
        }
      };
      timer.current = setTimeout(() => void tick(), 800);
    },
    [base, reload, handleError],
  );

  useEffect(() => {
    let active = true;
    Promise.all([fetchAll(), api<Job[]>(`${base}/jobs?limit=1`)])
      .then(([data, jobs]) => {
        if (!active) return;
        apply(data);
        const last = jobs[0];
        if (last && (last.status === "queued" || last.status === "running"))
          follow(last);
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [base, fetchAll, apply, follow, handleError]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await action();
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy(false);
    }
  }
  const start = (path: string, body?: object) =>
    run(async () =>
      follow(
        await api<Job>(`${base}${path}`, {
          method: "POST",
          body: JSON.stringify(body ?? {}),
        }),
      ),
    );
  const saveSyllabus = () =>
    run(async () => {
      const saved = await api<Syllabus>(`${base}/syllabus`, {
        method: "PUT",
        body: JSON.stringify({
          expected_revision: syllabus?.revision ?? 0,
          units: units.map((u) => ({
            ...(u.id ? { id: u.id } : {}),
            title: u.title,
            summary: u.summary,
            topics: u.topics
              .split("\n")
              .map((t) => t.trim())
              .filter(Boolean),
            ...(u.weeks ? { weeks: u.weeks } : {}),
          })),
        }),
      });
      setSyllabus(saved);
      setUnits(toEdit(saved));
      setDirty(false);
      setRefresh((r) => r + 1);
      setSuccess("Syllabus saved.");
    });
  const setStatus = (path: "approve" | "reopen") =>
    run(async () => {
      const saved = await api<Syllabus>(`${base}/syllabus/${path}`, {
        method: "POST",
        body: JSON.stringify({ expected_revision: syllabus?.revision ?? 0 }),
      });
      setSyllabus(saved);
      setUnits(toEdit(saved));
      setSuccess(
        path === "approve"
          ? "Syllabus approved. You can now generate notes."
          : "Syllabus reopened for editing.",
      );
    });
  function edit(index: number, change: Partial<EditUnit>) {
    setUnits((current) =>
      current.map((u, i) => (i === index ? { ...u, ...change } : u)),
    );
    setDirty(true);
  }
  function move(index: number, by: number) {
    setUnits((current) => {
      const next = [...current];
      const [item] = next.splice(index, 1);
      next.splice(index + by, 0, item);
      return next;
    });
    setDirty(true);
  }

  if (loading)
    return (
      <p className="loading" role="status">
        Loading syllabus…
      </p>
    );
  const running = !!job;
  const approved = syllabus?.status === "approved";
  return (
    <>
      <Link className="back-link" href={base}>
        ← {workspace?.title ?? "Course"}
      </Link>
      <div className="page-heading workspace-heading">
        <p className="eyebrow">Course content</p>
        <h1>Syllabus &amp; materials</h1>
        <p className="muted">
          Draft a syllabus from your extracted sources, approve it, then
          generate unit notes. Every claim cites a source passage, such as [C3].
        </p>
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
      {job && (
        <div className="notice job-status" role="status">
          <strong>{JOB_LABELS[job.kind] ?? "Working"}…</strong>{" "}
          {job.total ? `${job.progress} of ${job.total}` : job.status}
          <progress max={job.total || 1} value={job.progress} />
        </div>
      )}

      <section className="panel" aria-labelledby="syllabus-heading">
        <div className="section-heading">
          <h2 id="syllabus-heading">Syllabus</h2>
          {syllabus && (
            <span className={`count${approved ? "" : " count-draft"}`}>
              {approved
                ? `Approved ${formatDateTime(syllabus.approved_at)}`
                : "Draft"}
            </span>
          )}
        </div>
        {!syllabus && units.length === 0 ? (
          <div className="empty-state compact">
            <h3>No syllabus yet</h3>
            <p>
              Draft one from this course&apos;s extracted sources, or write it
              yourself.
            </p>
            <div className="button-row centered">
              <button
                disabled={busy || running}
                onClick={() => void start("/syllabus/generate")}
              >
                Generate syllabus
              </button>
              <button
                className="secondary"
                disabled={busy || running}
                onClick={() => {
                  setUnits([
                    {
                      title: "",
                      summary: "",
                      topics: "",
                      weeks: null,
                      citations: {},
                    },
                  ]);
                  setDirty(true);
                }}
              >
                Write it myself
              </button>
            </div>
          </div>
        ) : approved ? (
          <>
            <ol className="unit-list">
              {syllabus.units.map((u) => (
                <li key={u.id}>
                  <h3>{u.title}</h3>
                  {u.summary && <p className="muted">{u.summary}</p>}
                  {u.topics.length > 0 && (
                    <p className="topics">{u.topics.join(" · ")}</p>
                  )}
                  <UnitMeta weeks={u.weeks} citations={u.citations} />
                </li>
              ))}
            </ol>
            <button
              className="secondary"
              disabled={busy || running}
              onClick={() => void setStatus("reopen")}
            >
              Reopen to edit
            </button>
          </>
        ) : (
          <>
            <ol className="unit-editor">
              {units.map((u, i) => (
                <li key={u.id ?? `new-${i}`} className="unit-card">
                  <div className="unit-card-head">
                    <strong>Unit {i + 1}</strong>
                    <span>
                      <button
                        className="text-button"
                        disabled={i === 0}
                        onClick={() => move(i, -1)}
                        aria-label={`Move unit ${i + 1} up`}
                      >
                        ↑
                      </button>{" "}
                      <button
                        className="text-button"
                        disabled={i === units.length - 1}
                        onClick={() => move(i, 1)}
                        aria-label={`Move unit ${i + 1} down`}
                      >
                        ↓
                      </button>{" "}
                      <button
                        className="text-button danger"
                        onClick={() => {
                          if (
                            u.id &&
                            !window.confirm(
                              "Remove this unit? Its notes are deleted when you save.",
                            )
                          )
                            return;
                          setUnits((c) => c.filter((_, j) => j !== i));
                          setDirty(true);
                        }}
                      >
                        Remove
                      </button>
                    </span>
                  </div>
                  <label>
                    Title
                    <input
                      required
                      maxLength={200}
                      value={u.title}
                      onChange={(e) => edit(i, { title: e.target.value })}
                    />
                  </label>
                  <label>
                    Summary <span className="optional">(optional)</span>
                    <textarea
                      rows={2}
                      maxLength={2000}
                      value={u.summary}
                      onChange={(e) => edit(i, { summary: e.target.value })}
                    />
                  </label>
                  <label>
                    Topics <span className="optional">(one per line)</span>
                    <textarea
                      rows={3}
                      value={u.topics}
                      onChange={(e) => edit(i, { topics: e.target.value })}
                    />
                  </label>
                  <label className="weeks-input">
                    Weeks <span className="optional">(optional)</span>
                    <input
                      type="number"
                      min={1}
                      max={52}
                      value={u.weeks ?? ""}
                      onChange={(e) =>
                        edit(i, {
                          weeks: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    />
                  </label>
                  <UnitMeta weeks={null} citations={u.citations} />
                </li>
              ))}
            </ol>
            <div className="button-row">
              <button
                className="secondary"
                disabled={units.length >= 20}
                onClick={() => {
                  setUnits((c) => [
                    ...c,
                    {
                      title: "",
                      summary: "",
                      topics: "",
                      weeks: null,
                      citations: {},
                    },
                  ]);
                  setDirty(true);
                }}
              >
                Add unit
              </button>
              <button
                disabled={
                  busy ||
                  running ||
                  !dirty ||
                  units.some((u) => !u.title.trim())
                }
                onClick={() => void saveSyllabus()}
              >
                Save syllabus
              </button>
              <button
                disabled={busy || running || dirty || !syllabus?.units.length}
                title={dirty ? "Save your changes first" : undefined}
                onClick={() => void setStatus("approve")}
              >
                Approve
              </button>
              <button
                className="secondary"
                disabled={busy || running}
                onClick={() => {
                  if (
                    !syllabus ||
                    window.confirm(
                      "Regenerate the syllabus from sources? This replaces all units and deletes their notes.",
                    )
                  )
                    void start("/syllabus/generate");
                }}
              >
                Regenerate from sources
              </button>
            </div>
            {dirty && <p className="muted">You have unsaved changes.</p>}
          </>
        )}
      </section>

      <ResearchPanel
        base={base}
        disabled={busy || running}
        refresh={refresh}
        onRun={() => void start("/research")}
      />

      {approved && (
        <>
          <PublishPanel base={base} refresh={refresh} />
          <MaterialsSection
            base={base}
            hasLab={!!workspace?.has_lab}
            disabled={busy || running}
            refresh={refresh}
            onGenerate={(kind, unitIds) =>
              void start("/artifacts/generate", {
                kind,
                ...(unitIds ? { unit_ids: unitIds } : {}),
              })
            }
          />
          <ConceptGraphView
            base={base}
            disabled={busy || running}
            refresh={refresh}
            onBuild={() => void start("/concepts/build")}
          />
        </>
      )}
    </>
  );
}

export default function SyllabusPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <Protected roles={["teacher"]}>
      <CourseContent id={id} />
    </Protected>
  );
}
