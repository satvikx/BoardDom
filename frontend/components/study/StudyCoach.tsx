"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRequestError } from "../AuthProvider";
import { CitationList } from "../CitationList";
import { Markdown } from "../Markdown";
import { api, type ChatMessage } from "@/lib/api";

export function StudyCoach({ base }: { base: string }) {
  const handleError = useRequestError();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let active = true;
    api<ChatMessage[]>(`${base}/coach`)
      .then((data) => {
        if (active) setMessages(data);
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [base, handleError]);
  useEffect(
    () => end.current?.scrollIntoView({ block: "nearest" }),
    [messages],
  );
  async function send(event: FormEvent) {
    event.preventDefault();
    const message = text.trim();
    if (!message) return;
    setBusy(true);
    setError("");
    try {
      const turn = await api<{ question: ChatMessage; reply: ChatMessage }>(
        `${base}/coach`,
        { method: "POST", body: JSON.stringify({ message }) },
      );
      setMessages((m) => [...m, turn.question, turn.reply]);
      setText("");
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy(false);
    }
  }
  async function clear() {
    if (!window.confirm("Clear this conversation?")) return;
    try {
      await api<void>(`${base}/coach`, { method: "DELETE" });
      setMessages([]);
    } catch (e) {
      setError(handleError(e));
    }
  }
  return (
    <section className="panel" aria-labelledby="coach-heading">
      <div className="section-heading">
        <h2 id="coach-heading">Exam-prep coach</h2>
        {messages.length > 0 && (
          <button className="text-button" onClick={() => void clear()}>
            Clear chat
          </button>
        )}
      </div>
      <p className="muted">
        Tell me what you already know, for example “I know photosynthesis, what
        else do I need?”. I only use this course&apos;s material and show where
        each point comes from.
      </p>
      <div className="chat" aria-live="polite">
        {messages.map((m) =>
          m.role === "student" ? (
            <div key={m.id} className="bubble bubble-student">
              {m.content}
            </div>
          ) : (
            <div
              key={m.id}
              className={`bubble bubble-coach${m.in_scope ? "" : " out-of-scope"}`}
            >
              {m.known.length > 0 && (
                <p className="small-print">You know: {m.known.join(", ")}</p>
              )}
              <Markdown text={m.content} citations={Object.keys(m.citations)} />
              {m.checklist.length > 0 && (
                <>
                  <p className="eyebrow">Your checklist, in order</p>
                  <ol className="checklist">
                    {m.checklist.map((c, i) => (
                      <li key={i}>
                        <strong>{c.item}</strong>
                        <Markdown
                          text={c.why}
                          citations={Object.keys(m.citations)}
                        />
                      </li>
                    ))}
                  </ol>
                </>
              )}
              <CitationList citations={m.citations} title="Sources" />
            </div>
          ),
        )}
        <div ref={end} />
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <form onSubmit={send} className="chat-form">
        <label className="sr-only" htmlFor="coach-input">
          Message the coach
        </label>
        <textarea
          id="coach-input"
          rows={2}
          maxLength={2000}
          value={text}
          disabled={busy}
          placeholder="I know… what else do I need?"
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" disabled={busy || !text.trim()}>
          {busy ? "Thinking…" : "Send"}
        </button>
      </form>
    </section>
  );
}
