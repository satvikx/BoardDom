"use client";
import { useEffect, useState } from "react";
import { useRequestError } from "../AuthProvider";
import { CitationList } from "../CitationList";
import { Markdown } from "../Markdown";
import { api, formatDateTime, type Quiz, type StudentUnit } from "@/lib/api";

type Summary = Omit<Quiz, "questions">;

export function StudyQuiz({
  base,
  units,
}: {
  base: string;
  units: StudentUnit[];
}) {
  const handleError = useRequestError();
  const [unitId, setUnitId] = useState("");
  const [difficulty, setDifficulty] = useState<Quiz["difficulty"]>("medium");
  const [count, setCount] = useState(5);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [answers, setAnswers] = useState<(number | null)[]>([]);
  const [history, setHistory] = useState<Summary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let active = true;
    api<Summary[]>(`${base}/quizzes`)
      .then((data) => {
        if (active) setHistory(data);
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [base, tick, handleError]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy(false);
    }
  }
  const start = () =>
    run(async () => {
      const made = await api<Quiz>(`${base}/quizzes`, {
        method: "POST",
        body: JSON.stringify({
          difficulty,
          count,
          ...(unitId ? { unit_id: unitId } : {}),
        }),
      });
      setQuiz(made);
      setAnswers(made.questions.map(() => null));
    });
  const submit = () =>
    run(async () => {
      if (!quiz) return;
      setQuiz(
        await api<Quiz>(`/student/quizzes/${quiz.id}/submit`, {
          method: "POST",
          body: JSON.stringify({ answers }),
        }),
      );
      setTick((t) => t + 1);
    });
  const open = (id: string) =>
    run(async () => {
      const found = await api<Quiz>(`/student/quizzes/${id}`);
      setQuiz(found);
      setAnswers(found.questions.map((q) => q.chosen));
    });
  const done = !!quiz?.submitted_at;
  const sources = Object.assign(
    {},
    ...(quiz?.questions.map((q) => q.sources ?? {}) ?? []),
  );
  return (
    <section className="panel" aria-labelledby="quiz-heading">
      <div className="section-heading">
        <h2 id="quiz-heading">Quiz</h2>
        {quiz && (
          <button className="text-button" onClick={() => setQuiz(null)}>
            New quiz
          </button>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!quiz ? (
        <>
          <div className="form-row three">
            <label>
              Unit
              <select
                value={unitId}
                onChange={(e) => setUnitId(e.target.value)}
              >
                <option value="">Whole course</option>
                {units
                  .filter((u) => u.has_notes)
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.title}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Difficulty
              <select
                value={difficulty}
                onChange={(e) =>
                  setDifficulty(e.target.value as Quiz["difficulty"])
                }
              >
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>
            </label>
            <label>
              Questions
              <input
                type="number"
                min={3}
                max={10}
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
              />
            </label>
          </div>
          <button disabled={busy} onClick={() => void start()}>
            {busy ? "Writing your quiz…" : "Start quiz"}
          </button>
          {history.length > 0 && (
            <>
              <h3 className="subheading">Your past quizzes</h3>
              <ul className="version-list">
                {history.map((h) => (
                  <li key={h.id}>
                    <button
                      className="text-button"
                      onClick={() => void open(h.id)}
                    >
                      {h.unit_title ?? "Whole course"} · {h.difficulty}
                    </button>{" "}
                    <span className="muted">
                      {h.score === null
                        ? "not submitted"
                        : `${h.score} / ${h.total}`}{" "}
                      · {formatDateTime(h.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      ) : (
        <>
          {done && (
            <p className="notice" role="status">
              You scored <strong>{quiz.score}</strong> out of {quiz.total}.
            </p>
          )}
          <ol className="quiz">
            {quiz.questions.map((q, i) => (
              <li key={i}>
                <fieldset disabled={done || busy}>
                  <legend>{q.question}</legend>
                  {q.options.map((option, j) => {
                    const mark = done
                      ? j === q.answer_index
                        ? " right"
                        : j === q.chosen
                          ? " wrong"
                          : ""
                      : "";
                    return (
                      <label key={j} className={`check-row option${mark}`}>
                        <input
                          type="radio"
                          name={`q${i}`}
                          checked={answers[i] === j}
                          onChange={() =>
                            setAnswers((a) =>
                              a.map((v, k) => (k === i ? j : v)),
                            )
                          }
                        />
                        {option}
                      </label>
                    );
                  })}
                </fieldset>
                {done && q.explanation && (
                  <Markdown
                    text={`${q.correct ? "✓ Correct." : "✗ Not quite."} ${q.explanation}`}
                    citations={Object.keys(q.sources ?? {})}
                  />
                )}
              </li>
            ))}
          </ol>
          {!done && (
            <button disabled={busy} onClick={() => void submit()}>
              {busy ? "Marking…" : "Submit answers"}
            </button>
          )}
          {done && <CitationList citations={sources} />}
        </>
      )}
    </section>
  );
}
