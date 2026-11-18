"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Protected, useAuth, useRequestError } from "@/components/AuthProvider";
import { api, homeFor, type User } from "@/lib/api";

function ChangePassword() {
  const { user, setUser } = useAuth();
  const router = useRouter();
  const handleError = useRequestError();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const forced = !!user?.must_change_password;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setError("");
    setSuccess("");
    if (form.get("new_password") !== form.get("confirm_password")) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const updated = await api<User>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: form.get("current_password"),
          new_password: form.get("new_password"),
        }),
      });
      setUser(updated);
      formElement.reset();
      if (forced) router.push(homeFor(updated));
      else setSuccess("Password changed. Other browsers have been signed out.");
    } catch (e) {
      setError(handleError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-layout">
      <section className="auth-intro">
        <p className="eyebrow">Your account</p>
        <h1>
          {forced ? "Choose your own password." : "Change your password."}
        </h1>
        <p>
          {forced
            ? "You signed in with a temporary password. Pick a new one to continue."
            : "Changing it signs out your other browsers."}
        </p>
      </section>
      <section className="panel auth-panel">
        <h2>{forced ? "Set a new password" : "Change password"}</h2>
        <p className="muted">Signed in as {user?.email}</p>
        {forced && (
          <p role="status" className="notice">
            You need to change your temporary password before you can use
            Boardom.
          </p>
        )}
        <form onSubmit={submit}>
          <fieldset disabled={busy}>
            <label>
              {forced ? "Temporary password" : "Current password"}
              <input
                name="current_password"
                type="password"
                autoComplete="current-password"
                required
                maxLength={128}
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
                aria-describedby="new-password-help"
              />
            </label>
            <small id="new-password-help" className="muted">
              8–128 characters, different from the current one.
            </small>
            <label className="spaced-label">
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
            {success && (
              <p className="notice" role="status">
                {success}
              </p>
            )}
            <button className="full-width" type="submit">
              {busy ? "Please wait…" : "Change password"}
            </button>
          </fieldset>
        </form>
      </section>
    </div>
  );
}
export default function ChangePasswordPage() {
  return (
    <Protected passwordChangePage>
      <ChangePassword />
    </Protected>
  );
}
