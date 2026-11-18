"use client";
import { useEffect, useState } from "react";
import { useRequestError } from "../AuthProvider";
import { CitationList } from "../CitationList";
import { Markdown } from "../Markdown";
import {
  api,
  type StudentUnit,
  type StudyAid,
  type StudyAidTool,
} from "@/lib/api";

const TITLES: Record<StudyAidTool, string> = {
  mind_map: "Mind map",
  short_notes: "Short notes",
  flashcards: "Flashcards",
};

export function UnitPicker({
  units,
  value,
  onChange,
}: {
  units: StudentUnit[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <label className="unit-picker">
      Unit
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {units.map((u) => (
          <option key={u.id} value={u.id}>
            {u.title}
          </option>
        ))}
      </select>
    </label>
  );
}

export function StudyAids({
  base,
  units,
  tool,
}: {
  base: string;
  units: StudentUnit[];
  tool: StudyAidTool;
}) {
  const handleError = useRequestError();
  const withNotes = units.filter((u) => u.has_notes);
  const [unitId, setUnitId] = useState(withNotes[0]?.id ?? "");
  const [aid, setAid] = useState<StudyAid | null>(null);
  const [error, setError] = useState("");
  const [flipped, setFlipped] = useState<Set<number>>(new Set());
  useEffect(() => {
    if (!unitId) return;
    let active = true;
    api<StudyAid>(`${base}/units/${unitId}/aids/${tool}`, { method: "POST" })
      .then((data) => {
        if (active) {
          setAid(data);
          setError("");
          setFlipped(new Set());
        }
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [base, unitId, tool, handleError]);
  const labels = Object.keys(aid?.citations ?? {});
  const ready = aid && aid.tool === tool && aid.unit_id === unitId;
  return (
    <section className="panel" aria-labelledby="aid-heading">
      <div className="section-heading">
        <h2 id="aid-heading">{TITLES[tool]}</h2>
      </div>
      {withNotes.length === 0 ? (
        <p className="muted">No unit notes are published yet.</p>
      ) : (
        <UnitPicker units={withNotes} value={unitId} onChange={setUnitId} />
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!ready && !error && withNotes.length > 0 && (
        <p role="status" className="muted">
          Preparing your {TITLES[tool].toLowerCase()}…
        </p>
      )}
      {ready && tool === "mind_map" && (
        <div className="mind-map">
          <div className="mind-center">{aid.content.central}</div>
          <div className="mind-branches">
            {aid.content.branches?.map((b, i) => (
              <div className="mind-branch" key={i}>
                <h3>{b.label}</h3>
                <ul>
                  {b.children.map((c, j) => (
                    <li key={j}>{c}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
      {ready && tool === "short_notes" && (
        <ul className="short-notes">
          {aid.content.points?.map((p, i) => (
            <li key={i}>
              <Markdown text={p} citations={labels} />
            </li>
          ))}
        </ul>
      )}
      {ready && tool === "flashcards" && (
        <>
          <p className="muted small-print">Click a card to flip it.</p>
          <div className="flashcards">
            {aid.content.cards?.map((c, i) => {
              const back = flipped.has(i);
              return (
                <button
                  key={i}
                  className={`flashcard${back ? " flipped" : ""}`}
                  aria-pressed={back}
                  onClick={() =>
                    setFlipped((f) => {
                      const next = new Set(f);
                      if (next.has(i)) next.delete(i);
                      else next.add(i);
                      return next;
                    })
                  }
                >
                  <span className="eyebrow">
                    {back ? "Answer" : "Question"}
                  </span>
                  {back ? (
                    <Markdown text={c.back} citations={labels} />
                  ) : (
                    <span>{c.front}</span>
                  )}
                </button>
              );
            })}
          </div>
        </>
      )}
      {ready && <CitationList citations={aid.citations} />}
    </section>
  );
}
