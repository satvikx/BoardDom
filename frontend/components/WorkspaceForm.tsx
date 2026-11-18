"use client";
import { useState, type FormEvent } from "react";
import type { WorkspaceInput } from "@/lib/api";

export function WorkspaceForm({
  initial,
  busy,
  onSave,
  submitLabel,
}: {
  initial?: WorkspaceInput;
  busy: boolean;
  onSave: (value: WorkspaceInput) => Promise<void>;
  submitLabel: string;
}) {
  const [value, setValue] = useState<WorkspaceInput>(
    initial ?? {
      title: "",
      description: "",
      subject: "",
      learner_level: "introductory",
      lesson_duration_minutes: 40,
      has_lab: false,
    },
  );
  function submit(event: FormEvent) {
    event.preventDefault();
    void onSave({
      learner_level: value.learner_level,
      lesson_duration_minutes: value.lesson_duration_minutes,
      has_lab: !!value.has_lab,
      title: value.title.trim(),
      description: value.description?.trim() || null,
      subject: value.subject?.trim() || null,
    });
  }
  return (
    <form onSubmit={submit}>
      <fieldset disabled={busy}>
        <label>
          Workspace title
          <input
            required
            maxLength={200}
            value={value.title}
            placeholder="e.g. Introduction to ecosystems"
            onChange={(e) => setValue({ ...value, title: e.target.value })}
          />
        </label>
        <label>
          Subject <span className="optional">(optional)</span>
          <input
            maxLength={100}
            value={value.subject ?? ""}
            placeholder="e.g. Biology"
            onChange={(e) => setValue({ ...value, subject: e.target.value })}
          />
        </label>
        <div className="form-row">
          <label>
            Learner level
            <select
              value={value.learner_level}
              onChange={(e) =>
                setValue({
                  ...value,
                  learner_level: e.target
                    .value as WorkspaceInput["learner_level"],
                })
              }
            >
              <option value="introductory">Introductory</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
            </select>
          </label>
          <label>
            Duration (minutes)
            <input
              type="number"
              required
              min={1}
              max={1440}
              step={1}
              value={value.lesson_duration_minutes || ""}
              onChange={(e) =>
                setValue({
                  ...value,
                  lesson_duration_minutes: Number(e.target.value),
                })
              }
            />
          </label>
        </div>
        <label>
          <span className="check-row inline-check">
            <input
              type="checkbox"
              checked={!!value.has_lab}
              onChange={(e) =>
                setValue({ ...value, has_lab: e.target.checked })
              }
            />
            Has a lab (adds lab manuals)
          </span>
        </label>
        <label>
          Description <span className="optional">(optional)</span>
          <textarea
            rows={3}
            maxLength={5000}
            value={value.description ?? ""}
            placeholder="What will your learners explore?"
            onChange={(e) =>
              setValue({ ...value, description: e.target.value })
            }
          />
        </label>
        <button type="submit" disabled={!value.title.trim()}>
          {busy ? "Saving…" : submitLabel}
        </button>
      </fieldset>
    </form>
  );
}
