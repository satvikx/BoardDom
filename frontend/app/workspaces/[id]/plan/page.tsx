"use client";
import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Protected, useRequestError } from "@/components/AuthProvider";
import {
  CourseWizard,
  EMPTY_WIZARD,
  type WizardValue,
} from "@/components/CourseWizard";
import { api, type CourseProfile, type Workspace } from "@/lib/api";

function EditPlan({ id }: { id: string }) {
  const router = useRouter();
  const handleError = useRequestError();
  const base = `/workspaces/${id}`;
  const [initial, setInitial] = useState<WizardValue | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    Promise.all([
      api<Workspace>(base),
      api<CourseProfile | null>(`${base}/profile`),
    ])
      .then(([w, profile]) => {
        if (!active) return;
        const fallback = {
          ...EMPTY_WIZARD.profile,
          // Courses created before the wizard keep their "Has a lab" setting.
          ...(w.has_lab
            ? {
                mode: "theory_lab" as const,
                lab_hours_per_week: 2,
                experiments: 6,
              }
            : {}),
        };
        setInitial({
          title: w.title,
          subject: w.subject ?? "",
          description: w.description ?? "",
          learner_level: w.learner_level,
          lesson_duration_minutes: w.lesson_duration_minutes,
          profile: profile ?? fallback,
        });
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [base, handleError]);
  async function save(value: WizardValue) {
    setBusy(true);
    setError("");
    try {
      await api<Workspace>(base, {
        method: "PATCH",
        body: JSON.stringify({
          title: value.title,
          subject: value.subject,
          description: value.description || null,
          learner_level: value.learner_level,
          lesson_duration_minutes: value.lesson_duration_minutes,
        }),
      });
      await api<CourseProfile>(`${base}/profile`, {
        method: "PUT",
        body: JSON.stringify(value.profile),
      });
      router.push(base);
    } catch (e) {
      setError(handleError(e));
      setBusy(false);
    }
  }
  return (
    <>
      <Link className="back-link" href={base}>
        ← Back to the course
      </Link>
      <div className="page-heading workspace-heading">
        <p className="eyebrow">Course plan</p>
        <h1>Edit course details</h1>
        <p className="muted">
          Regenerate the syllabus afterwards to apply a changed plan.
        </p>
      </div>
      {initial ? (
        <CourseWizard
          initial={initial}
          busy={busy}
          submitLabel="Save plan"
          serverError={error}
          onSubmit={(v) => void save(v)}
        />
      ) : error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : (
        <p className="loading" role="status">
          Loading…
        </p>
      )}
    </>
  );
}

export default function EditPlanPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <Protected roles={["teacher"]}>
      <EditPlan id={id} />
    </Protected>
  );
}
