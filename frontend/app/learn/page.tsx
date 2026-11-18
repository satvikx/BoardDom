"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Protected, useAuth, useRequestError } from "@/components/AuthProvider";
import { api, type Course } from "@/lib/api";

function Learn() {
  const { user } = useAuth();
  const handleError = useRequestError();
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    api<Course[]>("/student/courses")
      .then((data) => {
        if (active) {
          setCourses(data);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [handleError, retry]);
  return (
    <>
      <div className="page-heading">
        <p className="eyebrow">Your learning</p>
        <h1>Hello, {user?.display_name}.</h1>
        <p className="muted">
          Courses your teacher has published. Open one to study.
        </p>
      </div>
      <section aria-labelledby="course-list">
        <div className="section-heading">
          <h2 id="course-list">My courses</h2>
          <span className="count">{courses.length}</span>
        </div>
        {loading ? (
          <p role="status">Loading courses…</p>
        ) : error ? (
          <div className="panel">
            <p className="error" role="alert">
              {error}
            </p>
            <button
              onClick={() => {
                setLoading(true);
                setRetry(retry + 1);
              }}
            >
              Retry
            </button>
          </div>
        ) : courses.length === 0 ? (
          <div className="empty-state">
            <span className="empty-mark" aria-hidden="true">
              ☺
            </span>
            <h3>Your teacher hasn&apos;t published a course yet</h3>
            <p>When they do, your courses will appear here.</p>
          </div>
        ) : (
          <div className="course-grid">
            {courses.map((c) => (
              <Link
                className="workspace-card"
                key={c.id}
                href={`/learn/${c.id}`}
              >
                <div>
                  <span className="tag">{c.subject || "Course"}</span>{" "}
                  {c.assigned && <span className="tag">Assigned to you</span>}
                  <h3>{c.title}</h3>
                  <p>
                    {c.learner_level} <span aria-hidden="true">·</span>{" "}
                    {c.lesson_duration_minutes} min{" "}
                    <span aria-hidden="true">·</span> {c.teacher_name}
                  </p>
                  {c.description && (
                    <p className="course-description">{c.description}</p>
                  )}
                  <progress
                    className="course-progress"
                    max={c.units_total || 1}
                    value={c.units_done}
                    aria-label="Units studied"
                  />
                  <small>
                    {c.units_done} of {c.units_total} units studied
                  </small>
                </div>
                <span aria-hidden="true" className="card-arrow">
                  ↗
                </span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
export default function LearnPage() {
  return (
    <Protected roles={["student"]}>
      <Learn />
    </Protected>
  );
}
