export type User = { id: string; email: string; display_name: string };
export type WorkspaceInput = {
  title: string;
  description: string | null;
  subject: string | null;
  learner_level: "introductory" | "intermediate" | "advanced";
  lesson_duration_minutes: number;
};
export type Workspace = WorkspaceInput & {
  id: string;
  created_at: string;
  updated_at: string;
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
export function formatSize(bytes: number) {
  return bytes < 1024
    ? `${bytes} B`
    : bytes < 1024 * 1024
      ? `${(bytes / 1024).toFixed(1)} KiB`
      : `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}
