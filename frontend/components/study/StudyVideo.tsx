"use client";
import { useEffect, useState } from "react";
import { useRequestError } from "../AuthProvider";
import { UnitPicker } from "./StudyAids";
import { api, type StudentUnit, type VideoStatus } from "@/lib/api";

export function StudyVideo({
  base,
  units,
}: {
  base: string;
  units: StudentUnit[];
}) {
  const handleError = useRequestError();
  const withNotes = units.filter((u) => u.has_notes);
  const [unitId, setUnitId] = useState(withNotes[0]?.id ?? "");
  const [video, setVideo] = useState<VideoStatus | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const url = `${base}/units/${unitId}/video`;
  const working = video?.status === "queued" || video?.status === "running";
  // Load the status for the chosen unit, and again on every poll tick.
  useEffect(() => {
    if (!unitId) return;
    let active = true;
    api<VideoStatus>(url)
      .then((status) => {
        if (active) {
          setVideo(status);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(handleError(e));
      });
    return () => {
      active = false;
    };
  }, [unitId, url, tick, handleError]);
  // While the video is being made, check again every two seconds.
  useEffect(() => {
    if (!working) return;
    const timer = setTimeout(() => setTick((t) => t + 1), 2000);
    return () => clearTimeout(timer);
  }, [working, video]);
  async function make() {
    setError("");
    try {
      setVideo(await api<VideoStatus>(url, { method: "POST" }));
    } catch (e) {
      setError(handleError(e));
    }
  }
  return (
    <section className="panel" aria-labelledby="video-heading">
      <div className="section-heading">
        <h2 id="video-heading">Video</h2>
      </div>
      <p className="muted">
        A short narrated slideshow made from the unit notes. It takes a minute
        or so the first time; after that it is ready for everyone.
      </p>
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
      {video?.status === "ready" ? (
        <>
          <video
            key={`${unitId}-${video.notes_version}`}
            className="study-video"
            controls
            preload="metadata"
            src={`/api/v1${url}/file?v=${video.notes_version}`}
          />
          <p className="muted small-print">
            {video.slide_count} slides ·{" "}
            {Math.round(video.duration_seconds ?? 0)} s ·{" "}
            {video.has_audio ? "narrated" : "silent with captions"}
            {video.message ? ` · ${video.message}` : ""}
          </p>
        </>
      ) : working ? (
        <p className="notice" role="status">
          Making your video… this page updates when it is ready.
        </p>
      ) : (
        withNotes.length > 0 && (
          <>
            {video?.status === "failed" && (
              <p className="error" role="alert">
                {video.message ?? "The video could not be made."}
              </p>
            )}
            <button onClick={() => void make()}>
              {video?.status === "failed" ? "Try again" : "Make video"}
            </button>
          </>
        )
      )}
    </section>
  );
}
