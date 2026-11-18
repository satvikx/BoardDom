"use client";
import { useState, type FormEvent } from "react";
import Link from "next/link";
import { api, errorMessage } from "@/lib/api";

export default function AdminResetPage() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    if (form.get("new_password") !== form.get("confirm_password")) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api<{ detail: string }>("/auth/admin/reset-password", {
        method: "POST",
        body: JSON.stringify({
          email: form.get("email"),
          pin: form.get("pin"),
          new_password: form.get("new_password"),
        }),
      });
      setDone(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-layout">
      <section className="auth-intro">
        <p className="eyebrow">Administrator recovery</p>
        <h1>Reset the admin password.</h1>
        <p>
          Use the reset PIN from the server configuration
          (BOARDOM_ADMIN_RESET_PIN). Teachers and students should ask their
          administrator or teacher instead.
        </p>
      </section>
      <section className="panel auth-panel">
        <h2>Forgot admin password?</h2>
        {done ? (
          <>
            <p role="status" className="notice">
              Password updated. All admin sessions were signed out.
            </p>
            <Link className="button full-width" href="/login">
              Log in
            </Link>
          </>
        ) : (
          <>
            <p className="muted">
              After 5 wrong PINs, PIN reset is locked for 15 minutes.
            </p>
            <form onSubmit={submit}>
              <fieldset disabled={busy}>
                <label>
                  Admin email
                  <input
                    name="email"
                    type="email"
                    autoComplete="username"
                    required
                    maxLength={254}
                  />
                </label>
                <label>
                  Reset PIN
                  <input
                    name="pin"
                    type="password"
                    inputMode="numeric"
                    autoComplete="off"
                    required
                    maxLength={64}
                  />
                </label>
                <label>
                  New password
                  <input
                    name="new_password"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    maxLength={128}
                  />
                </label>
                <label>
                  Confirm new password
                  <input
                    name="confirm_password"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    maxLength={128}
                  />
                </label>
                {error && (
                  <p className="error" role="alert">
                    {error}
                  </p>
                )}
                <button className="full-width" type="submit">
                  {busy ? "Please wait…" : "Reset password"}
                </button>
              </fieldset>
            </form>
            <p className="auth-switch">
              <Link href="/login">Back to log in</Link>
            </p>
          </>
        )}
      </section>
    </div>
  );
}
