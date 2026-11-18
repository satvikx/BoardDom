"use client";
import { useEffect, useState, type FormEvent } from "react";
import { Protected, useAuth, useRequestError } from "@/components/AuthProvider";
import { TempPassword } from "@/components/TempPassword";
import { api, formatDateTime, type AdminUser, type Role } from "@/lib/api";

type Created = { user: AdminUser; temporary_password: string };

function LimitEditor({
  user,
  onSave,
  busy,
}: {
  user: AdminUser;
  onSave: (value: number) => Promise<void>;
  busy: boolean;
}) {
  const [value, setValue] = useState(String(user.student_limit ?? 0));
  const changed = value !== String(user.student_limit);
  return (
    <form
      className="inline-form"
      onSubmit={(e) => {
        e.preventDefault();
        void onSave(Number(value));
      }}
    >
      <label className="sr-only" htmlFor={`limit-${user.id}`}>
        Student limit for {user.display_name}
      </label>
      <input
        id={`limit-${user.id}`}
        type="number"
        min={0}
        max={10000}
        step={1}
        required
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
      />
      {changed && (
        <button className="small" type="submit" disabled={busy}>
          Save
        </button>
      )}
    </form>
  );
}

function deletionSummary(user: AdminUser, users: AdminUser[]) {
  if (user.role === "teacher") {
    const students = users
      .filter((u) => u.role === "student" && u.created_by_user_id === user.id)
      .map((u) => `  • ${u.display_name} (${u.email})`);
    return [
      `Delete teacher ${user.display_name} (${user.email})?`,
      "",
      "This permanently removes:",
      `• ${user.course_count ?? 0} course(s) and ${user.file_count ?? 0} uploaded file(s)`,
      `• ${user.student_count ?? 0} student account(s)${students.length ? ":" : ""}`,
      ...students,
      "• all of their enrollments and sessions",
      "",
      "This cannot be undone.",
    ].join("\n");
  }
  return [
    `Delete student ${user.display_name} (${user.email})?`,
    "",
    "This permanently removes the account and its",
    `${user.enrollment_count ?? 0} course enrollment(s). This cannot be undone.`,
  ].join("\n");
}

function AdminView() {
  const { user: me } = useAuth();
  const handleError = useRequestError();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [role, setRole] = useState<Role | "">("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [created, setCreated] = useState<Created | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams();
    if (role) params.set("role", role);
    if (query.trim()) params.set("q", query.trim());
    const timer = setTimeout(() => {
      api<AdminUser[]>(`/admin/users?${params}`)
        .then((data) => {
          if (!active) return;
          setUsers(data);
          setError("");
        })
        .catch((e) => {
          if (active) setError(handleError(e));
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [role, query, refresh, handleError]);
  function begin(action: string) {
    setBusy(action);
    setError("");
    setSuccess("");
  }
  async function addTeacher(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const limit = String(form.get("student_limit") ?? "").trim();
    begin("create");
    try {
      const result = await api<Created>("/admin/teachers", {
        method: "POST",
        body: JSON.stringify({
          display_name: form.get("display_name"),
          email: form.get("email"),
          student_limit: limit === "" ? null : Number(limit),
        }),
      });
      setCreated(result);
      formElement.reset();
      setRefresh((n) => n + 1);
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy("");
    }
  }
  async function saveLimit(user: AdminUser, value: number) {
    begin(user.id);
    try {
      const updated = await api<AdminUser>(`/admin/teachers/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify({ student_limit: value }),
      });
      setUsers((current) =>
        current.map((u) => (u.id === updated.id ? updated : u)),
      );
      setSuccess(
        updated.student_count !== null &&
          updated.student_count > (updated.student_limit ?? 0)
          ? `Limit saved. ${updated.display_name} has ${updated.student_count} students, above the new limit of ${updated.student_limit}; nobody was removed, but new students are blocked.`
          : `Student limit for ${updated.display_name} set to ${updated.student_limit}.`,
      );
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy("");
    }
  }
  async function remove(user: AdminUser) {
    if (!window.confirm(deletionSummary(user, users))) return;
    begin(user.id);
    try {
      await api<void>(`/admin/users/${user.id}`, { method: "DELETE" });
      setSuccess(`${user.display_name} was deleted.`);
      setRefresh((n) => n + 1);
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <div className="page-heading">
        <p className="eyebrow">Administration</p>
        <h1>People</h1>
        <p className="muted">
          Create teachers, set how many students each may add, and remove
          accounts.
        </p>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {success && (
        <p className="notice" role="status">
          {success}
        </p>
      )}
      <div className="dashboard-grid">
        <section aria-labelledby="users-heading">
          <div className="section-heading">
            <h2 id="users-heading">All users</h2>
            <span className="count">{users.length}</span>
          </div>
          <div className="filter-row">
            <label>
              Role
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as Role | "")}
              >
                <option value="">All roles</option>
                <option value="admin">Admins</option>
                <option value="teacher">Teachers</option>
                <option value="student">Students</option>
              </select>
            </label>
            <label>
              Search
              <input
                type="search"
                value={query}
                maxLength={254}
                placeholder="Name or email"
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
          </div>
          {loading ? (
            <p role="status">Loading users…</p>
          ) : users.length === 0 ? (
            <div className="empty-state compact">
              <h3>No matching users</h3>
              <p>Try another role or search.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col">Role</th>
                    <th scope="col">Created by</th>
                    <th scope="col">Students / teacher</th>
                    <th scope="col">Student limit</th>
                    <th scope="col">Last login</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id}>
                      <td>
                        <strong>{u.display_name}</strong>
                        <small className="cell-sub">{u.email}</small>
                      </td>
                      <td>
                        <span className="tag capitalize">{u.role}</span>
                        {u.must_change_password && (
                          <small className="cell-sub">Temporary password</small>
                        )}
                      </td>
                      <td>
                        {u.created_by_name ??
                          (u.role === "teacher" ? "Self sign-up" : "System")}
                      </td>
                      <td>
                        {u.role === "teacher"
                          ? `${u.student_count} student${u.student_count === 1 ? "" : "s"}`
                          : u.role === "student"
                            ? (u.created_by_name ?? "—")
                            : "—"}
                      </td>
                      <td>
                        {u.role === "teacher" ? (
                          <LimitEditor
                            key={`${u.id}-${u.student_limit}`}
                            user={u}
                            busy={busy === u.id}
                            onSave={(value) => saveLimit(u, value)}
                          />
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>{formatDateTime(u.last_login_at)}</td>
                      <td>
                        {u.role !== "admin" && u.id !== me?.id && (
                          <button
                            className="text-button danger"
                            disabled={!!busy}
                            onClick={() => void remove(u)}
                          >
                            Delete
                            <span className="sr-only"> {u.display_name}</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="panel create-panel">
          <p className="eyebrow">New account</p>
          <h2>Add teacher</h2>
          <p className="muted">
            Boardom generates a temporary password. The teacher must change it
            at first login.
          </p>
          {created && (
            <TempPassword
              name={created.user.display_name}
              email={created.user.email}
              password={created.temporary_password}
              onDismiss={() => setCreated(null)}
            />
          )}
          <form onSubmit={addTeacher}>
            <fieldset disabled={!!busy}>
              <label>
                Name
                <input
                  name="display_name"
                  required
                  maxLength={100}
                  placeholder="Alex Morgan"
                />
              </label>
              <label>
                Email address
                <input
                  name="email"
                  type="email"
                  required
                  maxLength={254}
                  placeholder="teacher@school.edu"
                />
              </label>
              <label>
                Student limit <span className="optional">(optional)</span>
                <input
                  name="student_limit"
                  type="number"
                  min={0}
                  max={10000}
                  step={1}
                  placeholder="Leave empty to use the default"
                />
              </label>
              <button type="submit">
                {busy === "create" ? "Creating…" : "Add teacher"}
              </button>
            </fieldset>
          </form>
        </section>
      </div>
    </>
  );
}
export default function AdminPage() {
  return (
    <Protected roles={["admin"]}>
      <AdminView />
    </Protected>
  );
}
