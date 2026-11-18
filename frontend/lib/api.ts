export type Role = "admin" | "teacher" | "student";
export type User = {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  must_change_password: boolean;
};
export type PublicConfig = {
  max_upload_bytes: number;
  allow_public_signup: boolean;
};
export const HOME: Record<Role, string> = {
  admin: "/admin",
  teacher: "/dashboard",
  student: "/learn",
};
export function homeFor(user: User) {
  return user.must_change_password ? "/change-password" : HOME[user.role];
}
export type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  created_at: string;
  last_login_at: string | null;
  must_change_password: boolean;
  created_by_user_id: string | null;
  created_by_name: string | null;
  student_count: number | null;
  student_limit: number | null;
  uses_default_limit: boolean | null;
  course_count: number | null;
  file_count: number | null;
  enrollment_count: number | null;
};
export type Student = {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
  last_login_at: string | null;
  must_change_password: boolean;
  course_count: number;
};
export type StudentList = { students: Student[]; used: number; limit: number };
export type Enrollment = {
  student_id: string;
  display_name: string;
  email: string;
  enrolled_at: string;
};
export type Course = {
  id: string;
  title: string;
  subject: string | null;
  description: string | null;
  learner_level: string;
  lesson_duration_minutes: number;
  has_lab: boolean;
  teacher_name: string;
  published_at: string;
  assigned: boolean;
  units_total: number;
  units_done: number;
};
export type StudentUnit = {
  id: string;
  position: number;
  title: string;
  summary: string;
  topics: string[];
  has_notes: boolean;
  has_lab_manual: boolean;
  studied: boolean;
};
export type CourseDetail = { course: Course; units: StudentUnit[] };
export type PublishedDoc = {
  unit_id: string;
  unit_title: string;
  version: number;
  markdown: string;
  citations: Record<string, Citation>;
};
export type ChatMessage = {
  id: string;
  role: "student" | "coach";
  content: string;
  in_scope: boolean;
  citations: Record<string, Citation>;
  checklist: { item: string; why: string }[];
  known: string[];
  created_at: string;
};
export type QuizQuestion = {
  question: string;
  options: string[];
  answer_index: number | null;
  chosen: number | null;
  correct: boolean | null;
  explanation: string | null;
  sources: Record<string, Citation> | null;
};
export type Quiz = {
  id: string;
  unit_title: string | null;
  difficulty: "easy" | "medium" | "hard";
  total: number;
  score: number | null;
  created_at: string;
  submitted_at: string | null;
  questions: QuizQuestion[];
};
export type StudyAidTool = "mind_map" | "short_notes" | "flashcards";
export type StudyAid = {
  tool: StudyAidTool;
  unit_id: string;
  notes_version: number;
  content: {
    central?: string;
    branches?: { label: string; children: string[] }[];
    points?: string[];
    cards?: { front: string; back: string }[];
  };
  citations: Record<string, Citation>;
};
export type VideoStatus = {
  status: "none" | "queued" | "running" | "ready" | "failed";
  message: string | null;
  has_audio: boolean;
  duration_seconds: number | null;
  slide_count: number;
  notes_version: number | null;
};
export type WorkspaceInput = {
  title: string;
  description: string | null;
  subject: string | null;
  learner_level: "introductory" | "intermediate" | "advanced";
  lesson_duration_minutes: number;
  has_lab: boolean;
};
export type Workspace = WorkspaceInput & {
  id: string;
  created_at: string;
  updated_at: string;
  published_at: string | null;
};
export type SourceDocument = {
  id: string;
  workspace_id: string;
  original_filename: string;
  media_type: string;
  size_bytes: number;
  status: "uploaded";
  extraction_status:
    "uploaded" | "processing" | "extracted" | "failed" | "needs_ocr";
  extraction_error_message: string | null;
  extraction_warnings: string[];
  reviewed_at: string | null;
  content_revision: number;
  created_at: string;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
async function request(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      0,
      "Unable to connect. Check your connection and try again.",
    );
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const message =
      typeof data?.detail === "string"
        ? data.detail
        : `Request failed (${response.status}). Please retry.`;
    throw new ApiError(response.status, message);
  }
  return response;
}
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await request(path, options);
  return response.status === 204 ? (undefined as T) : response.json();
}
export async function downloadDocument(
  workspaceId: string,
  document: SourceDocument,
  corrected = false,
) {
  const response = await request(
    `/workspaces/${workspaceId}/documents/${document.id}/${corrected ? "content/download" : "download"}`,
  );
  const url = URL.createObjectURL(await response.blob());
  const anchor = window.document.createElement("a");
  anchor.href = url;
  anchor.download =
    (corrected ? "corrected-" : "") +
      document.original_filename.replace(/\\/g, "/").split("/").pop() ||
    "document";
  window.document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function errorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please retry.";
}
export function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
export function formatDateTime(value: string | null) {
  return value
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "Never";
}
export function formatSize(bytes: number) {
  return bytes < 1024
    ? `${bytes} B`
    : bytes < 1024 * 1024
      ? `${(bytes / 1024).toFixed(1)} KiB`
      : `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}
export type Job = {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  total: number;
  message: string | null;
  created_at: string;
  finished_at: string | null;
};
export type SyllabusUnit = {
  id: string;
  position: number;
  title: string;
  summary: string;
  topics: string[];
  weeks: number | null;
  citations: Record<string, Citation>;
};
export type Syllabus = {
  id: string;
  status: "draft" | "approved";
  revision: number;
  approved_at: string | null;
  updated_at: string;
  units: SyllabusUnit[];
};
export type ArtifactKind =
  "unit_notes" | "lab_manual" | "lesson_plan" | "rubric";
export type NotesSummary = {
  kind: ArtifactKind;
  unit_id: string | null;
  unit_title: string;
  position: number;
  artifact_id: string | null;
  current_version: number;
  published_version: number | null;
  updated_at: string | null;
  warning_count: number;
};
export type Citation = {
  document: string;
  page: number | null;
  excerpt: string;
};
export type NotesVersionInfo = {
  number: number;
  origin: "generated" | "edited" | "restored";
  created_at: string;
  created_by_name: string | null;
};
export type Notes = {
  artifact_id: string;
  kind: ArtifactKind;
  unit_id: string | null;
  unit_title: string;
  number: number;
  current_version: number;
  published_version: number | null;
  origin: string;
  markdown: string;
  citations: Record<string, Citation>;
  warnings: string[];
  versions: NotesVersionInfo[];
};
export type ConceptNode = {
  id: string;
  name: string;
  description: string;
  unit_id: string | null;
  unit_title: string | null;
  level: number;
  prerequisite_ids: string[];
};
export type ConceptGraph = { concepts: ConceptNode[]; edge_count: number };
export type Publication = {
  published_at: string | null;
  unpublished_changes: boolean;
  units: {
    unit_id: string;
    title: string;
    notes_current: number;
    notes_published: number | null;
    lab_current: number;
    lab_published: number | null;
  }[];
};
export async function downloadFile(path: string, fallbackName: string) {
  const response = await request(path);
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  const name = match ? decodeURIComponent(match[1]) : fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const anchor = window.document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  window.document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export type AssessmentItem = { name: string; weight_percent: number };
export type CourseProfile = {
  audience: string;
  weeks: number;
  hours_per_week: number;
  mode: "theory" | "theory_lab";
  lab_hours_per_week: number;
  experiments: number;
  must_include: string[];
  exclude: string[];
  assessment: AssessmentItem[];
};
export type Finding = {
  id: string;
  label: string;
  query: string;
  title: string;
  url: string;
  summary: string;
  status: "pending" | "accepted" | "ignored";
  flagged: boolean;
  flag_reason: string | null;
  created_at: string;
};
