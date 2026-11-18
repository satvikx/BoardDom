"use client";
import { useState } from "react";
import type { AssessmentItem, CourseProfile, WorkspaceInput } from "@/lib/api";

export type WizardValue = {
  title: string;
  subject: string;
  description: string;
  learner_level: WorkspaceInput["learner_level"];
  lesson_duration_minutes: number;
  profile: CourseProfile;
};

export const EMPTY_WIZARD: WizardValue = {
  title: "",
  subject: "",
  description: "",
  learner_level: "introductory",
  lesson_duration_minutes: 60,
  profile: {
    audience: "",
    weeks: 10,
    hours_per_week: 3,
    mode: "theory",
    lab_hours_per_week: 0,
    experiments: 0,
    must_include: [],
    exclude: [],
    assessment: [
      { name: "Coursework", weight_percent: 40 },
      { name: "Final exam", weight_percent: 60 },
    ],
  },
};

const STEPS = [
  "Basics",
  "Audience & schedule",
  "Theory & lab",
  "Topics & assessment",
];

const lines = (text: string) =>
  text
    .split("\n")
    .map((t) => t.trim())
    .filter(Boolean);

const whole = (n: number, min: number, max: number) =>
  Number.isInteger(n) && n >= min && n <= max;

/** Same rules as the server (CourseProfileIn / WizardIn); returns problems for one step. */
export function validateStep(step: number, v: WizardValue): string[] {
  const p = v.profile;
  const errors: string[] = [];
  if (step === 0) {
    if (!v.title.trim()) errors.push("Enter a course title.");
    if (v.title.trim().length > 200)
      errors.push("The title is too long (200 max).");
    if (!v.subject.trim()) errors.push("Enter a subject.");
    if (!whole(v.lesson_duration_minutes, 1, 1440))
      errors.push("Session length must be a whole number of minutes (1–1440).");
  }
  if (step === 1) {
    if (!p.audience.trim()) errors.push("Describe the audience.");
    if (!whole(p.weeks, 1, 52))
      errors.push("Weeks must be a whole number from 1 to 52.");
    if (!whole(p.hours_per_week, 1, 40))
      errors.push("Hours per week must be a whole number from 1 to 40.");
  }
  if (step === 2 && p.mode === "theory_lab") {
    if (!whole(p.lab_hours_per_week, 1, 20))
      errors.push("Lab hours per week must be from 1 to 20.");
    if (!whole(p.experiments, 1, 30))
      errors.push("Number of experiments must be from 1 to 30.");
  }
  if (step === 3) {
    const include = new Set(p.must_include.map((t) => t.toLowerCase()));
    const both = p.exclude.filter((t) => include.has(t.toLowerCase()));
    if (both.length)
      errors.push(
        `Topics cannot be both required and excluded: ${both.join(", ")}.`,
      );
    if ([...p.must_include, ...p.exclude].some((t) => t.length > 100))
      errors.push("Each topic must be 100 characters or fewer.");
    if (p.must_include.length > 30 || p.exclude.length > 30)
      errors.push("List at most 30 topics in each box.");
    if (!p.assessment.length)
      errors.push("Add at least one assessment component.");
    if (p.assessment.some((a) => !a.name.trim()))
      errors.push("Name every assessment component.");
    const names = p.assessment.map((a) => a.name.trim().toLowerCase());
    if (new Set(names).size !== names.length)
      errors.push("Each assessment component needs a different name.");
    if (p.assessment.some((a) => !whole(a.weight_percent, 1, 100)))
      errors.push("Weights must be whole percentages from 1 to 100.");
    const total = p.assessment.reduce((s, a) => s + a.weight_percent, 0);
    if (total !== 100)
      errors.push(`Weights must add up to 100% (now ${total}%).`);
  }
  return errors;
}

export function CourseWizard({
  initial,
  busy,
  submitLabel,
  serverError,
  onSubmit,
}: {
  initial: WizardValue;
  busy: boolean;
  submitLabel: string;
  serverError: string;
  onSubmit: (value: WizardValue) => void;
}) {
  const [value, setValue] = useState<WizardValue>(initial);
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<string[]>([]);
  const [include, setInclude] = useState(
    initial.profile.must_include.join("\n"),
  );
  const [exclude, setExclude] = useState(initial.profile.exclude.join("\n"));
  const p = value.profile;
  const setProfile = (change: Partial<CourseProfile>) =>
    setValue((v) => ({ ...v, profile: { ...v.profile, ...change } }));
  const setAssessment = (i: number, change: Partial<AssessmentItem>) =>
    setProfile({
      assessment: p.assessment.map((a, j) =>
        j === i ? { ...a, ...change } : a,
      ),
    });
  function next() {
    const problems = validateStep(step, value);
    setErrors(problems);
    if (!problems.length) setStep((s) => s + 1);
  }
  function submit() {
    const problems = STEPS.flatMap((_, i) => validateStep(i, value));
    setErrors(problems);
    if (!problems.length)
      onSubmit({
        ...value,
        title: value.title.trim(),
        subject: value.subject.trim(),
        description: value.description.trim(),
        profile: {
          ...p,
          audience: p.audience.trim(),
          assessment: p.assessment.map((a) => ({ ...a, name: a.name.trim() })),
          ...(p.mode === "theory"
            ? { lab_hours_per_week: 0, experiments: 0 }
            : {}),
        },
      });
  }
  const total = p.assessment.reduce((s, a) => s + (a.weight_percent || 0), 0);
  return (
    <section className="panel wizard" aria-labelledby="wizard-step">
      <ol className="wizard-steps">
        {STEPS.map((name, i) => (
          <li
            key={name}
            className={i === step ? "current" : i < step ? "done" : ""}
            aria-current={i === step ? "step" : undefined}
          >
            <span>{i + 1}</span> {name}
          </li>
        ))}
      </ol>
      <h2 id="wizard-step">{STEPS[step]}</h2>
      <fieldset disabled={busy}>
        {step === 0 && (
          <>
            <label>
              Course title
              <input
                maxLength={200}
                value={value.title}
                placeholder="e.g. Energy in living things"
                onChange={(e) => setValue({ ...value, title: e.target.value })}
              />
            </label>
            <label>
              Subject
              <input
                maxLength={100}
                value={value.subject}
                placeholder="e.g. Biology"
                onChange={(e) =>
                  setValue({ ...value, subject: e.target.value })
                }
              />
            </label>
            <div className="form-row">
              <label>
                Difficulty
                <select
                  value={value.learner_level}
                  onChange={(e) =>
                    setValue({
                      ...value,
                      learner_level: e.target
                        .value as WizardValue["learner_level"],
                    })
                  }
                >
                  <option value="introductory">Introductory</option>
                  <option value="intermediate">Intermediate</option>
                  <option value="advanced">Advanced</option>
                </select>
              </label>
              <label>
                Session length (minutes)
                <input
                  type="number"
                  min={1}
                  max={1440}
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
              Description <span className="optional">(optional)</span>
              <textarea
                rows={3}
                maxLength={5000}
                value={value.description}
                onChange={(e) =>
                  setValue({ ...value, description: e.target.value })
                }
              />
            </label>
          </>
        )}
        {step === 1 && (
          <>
            <label>
              Audience
              <input
                maxLength={200}
                value={p.audience}
                placeholder="e.g. Year 10 students, mixed ability"
                onChange={(e) => setProfile({ audience: e.target.value })}
              />
            </label>
            <div className="form-row">
              <label>
                Duration (weeks)
                <input
                  type="number"
                  min={1}
                  max={52}
                  value={p.weeks || ""}
                  onChange={(e) =>
                    setProfile({ weeks: Number(e.target.value) })
                  }
                />
              </label>
              <label>
                Theory hours per week
                <input
                  type="number"
                  min={1}
                  max={40}
                  value={p.hours_per_week || ""}
                  onChange={(e) =>
                    setProfile({ hours_per_week: Number(e.target.value) })
                  }
                />
              </label>
            </div>
          </>
        )}
        {step === 2 && (
          <>
            <div
              className="choice-row"
              role="radiogroup"
              aria-label="Course type"
            >
              {(
                [
                  ["theory", "Theory only"],
                  ["theory_lab", "Theory + lab"],
                ] as const
              ).map(([mode, label]) => (
                <label key={mode} className="check-row">
                  <input
                    type="radio"
                    name="mode"
                    checked={p.mode === mode}
                    onChange={() =>
                      setProfile(
                        mode === "theory"
                          ? { mode, lab_hours_per_week: 0, experiments: 0 }
                          : {
                              mode,
                              lab_hours_per_week: p.lab_hours_per_week || 2,
                              experiments: p.experiments || 6,
                            },
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
            {p.mode === "theory_lab" ? (
              <div className="form-row">
                <label>
                  Lab hours per week
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={p.lab_hours_per_week || ""}
                    onChange={(e) =>
                      setProfile({ lab_hours_per_week: Number(e.target.value) })
                    }
                  />
                </label>
                <label>
                  Number of experiments
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={p.experiments || ""}
                    onChange={(e) =>
                      setProfile({ experiments: Number(e.target.value) })
                    }
                  />
                </label>
              </div>
            ) : (
              <p className="muted">No lab: lab manuals are not generated.</p>
            )}
          </>
        )}
        {step === 3 && (
          <>
            <div className="form-row">
              <label>
                Must include <span className="optional">(one per line)</span>
                <textarea
                  rows={4}
                  value={include}
                  onChange={(e) => {
                    setInclude(e.target.value);
                    setProfile({ must_include: lines(e.target.value) });
                  }}
                />
              </label>
              <label>
                Exclude <span className="optional">(one per line)</span>
                <textarea
                  rows={4}
                  value={exclude}
                  onChange={(e) => {
                    setExclude(e.target.value);
                    setProfile({ exclude: lines(e.target.value) });
                  }}
                />
              </label>
            </div>
            <p className="label-like">
              Assessment pattern{" "}
              <span className={total === 100 ? "count" : "count count-draft"}>
                {total}% of 100%
              </span>
            </p>
            {p.assessment.map((a, i) => (
              <div className="assessment-row" key={i}>
                <input
                  aria-label={`Component ${i + 1} name`}
                  maxLength={60}
                  value={a.name}
                  placeholder="e.g. Midterm"
                  onChange={(e) => setAssessment(i, { name: e.target.value })}
                />
                <input
                  aria-label={`Component ${i + 1} weight`}
                  type="number"
                  min={1}
                  max={100}
                  value={a.weight_percent || ""}
                  onChange={(e) =>
                    setAssessment(i, { weight_percent: Number(e.target.value) })
                  }
                />
                <span>%</span>
                <button
                  type="button"
                  className="text-button danger"
                  disabled={p.assessment.length === 1}
                  onClick={() =>
                    setProfile({
                      assessment: p.assessment.filter((_, j) => j !== i),
                    })
                  }
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              className="secondary"
              disabled={p.assessment.length >= 8}
              onClick={() =>
                setProfile({
                  assessment: [
                    ...p.assessment,
                    { name: "", weight_percent: 0 },
                  ],
                })
              }
            >
              Add component
            </button>
          </>
        )}
      </fieldset>
      {errors.length > 0 && (
        <ul className="error" role="alert">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {serverError && (
        <p className="error" role="alert">
          {serverError}
        </p>
      )}
      <div className="button-row">
        {step > 0 && (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => {
              setErrors([]);
              setStep(step - 1);
            }}
          >
            Back
          </button>
        )}
        {step < STEPS.length - 1 ? (
          <button type="button" disabled={busy} onClick={next}>
            Next
          </button>
        ) : (
          <button type="button" disabled={busy} onClick={submit}>
            {busy ? "Saving…" : submitLabel}
          </button>
        )}
      </div>
    </section>
  );
}
