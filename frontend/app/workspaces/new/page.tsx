"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Protected, useRequestError } from "@/components/AuthProvider";
import {
  CourseWizard,
  EMPTY_WIZARD,
  type WizardValue,
} from "@/components/CourseWizard";
import { api, type Workspace } from "@/lib/api";

function NewCourse() {
  const router = useRouter();
  const handleError = useRequestError();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function create(value: WizardValue) {
    setBusy(true);
    setError("");
    try {
      const course = await api<Workspace>("/workspaces/wizard", {
        method: "POST",
        body: JSON.stringify({
          ...value,
          description: value.description || null,
        }),
      });
      router.push(`/workspaces/${course.id}`);
    } catch (e) {
      setError(handleError(e));
      setBusy(false);
    }
  }
  return (
    <>
      <Link className="back-link" href="/dashboard">
        ← All courses
      </Link>
      <div className="page-heading workspace-heading">
        <p className="eyebrow">New course</p>
        <h1>Set up your course</h1>
        <p className="muted">
          Four short steps. The syllabus generator follows these answers.
        </p>
      </div>
      <CourseWizard
        initial={EMPTY_WIZARD}
        busy={busy}
        submitLabel="Create course"
        serverError={error}
        onSubmit={(v) => void create(v)}
      />
    </>
  );
}

export default function NewCoursePage() {
  return (
    <Protected roles={["teacher"]}>
      <NewCourse />
    </Protected>
  );
}
