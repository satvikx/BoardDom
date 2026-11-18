"use client";
import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, errorMessage, homeFor, type User } from "@/lib/api";
import { useAuth } from "./AuthProvider";

export function AuthForm({
  register = false,
  expired = false,
}: {
  register?: boolean;
  expired?: boolean;
}) {
  const { setUser, config } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const body = {
      email: form.get("email"),
      password: form.get("password"),
      ...(register ? { display_name: form.get("display_name") } : {}),
    };
    try {
      const user = await api<User>(`/auth/${register ? "register" : "login"}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setUser(user);
      router.push(homeFor(user));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  if (register && config && !config.allow_public_signup)
    return (
      <div className="auth-layout">
        <section className="auth-intro">
          <p className="eyebrow">Accounts by invitation</p>
          <h1>Sign-up is turned off.</h1>
          <p>
            Your administrator creates teacher accounts, and teachers create
            student accounts.
          </p>
        </section>
        <section className="panel auth-panel">
          <h2>Already have an account?</h2>
          <p className="muted">
            Use the email and temporary password you were given. You will choose
            your own password after logging in.
          </p>
          <Link className="button full-width" href="/login">
            Log in
          </Link>
        </section>
      </div>
    );
  return (
    <div className="auth-layout">
      <section className="auth-intro">
        <p className="eyebrow">A little more room to teach</p>
        <h1>
          {register
            ? "Good lessons start here."
            : "Back to your next great lesson."}
        </h1>
        <p>
          A home for your lesson ideas, notes, and source materials. Ready
          whenever you are.
        </p>
      </section>
      <section className="panel auth-panel">
        <h2>{register ? "Create your account" : "Welcome back"}</h2>
        <p className="muted">
          {register
            ? "Your teaching materials, together in one place."
            : "Log in to pick up where you left off."}
        </p>
        {expired && (
          <p role="status" className="notice">
            Your session expired. Log in again to continue.
          </p>
        )}
        <form onSubmit={submit}>
          <fieldset disabled={busy}>
            {register && (
              <label>
                Display name
                <input
                  name="display_name"
                  autoComplete="name"
                  required
                  maxLength={100}
                  placeholder="Alex Morgan"
                />
              </label>
            )}
            <label>
              Email address
              <input
                name="email"
                type="email"
                autoComplete="email"
                required
                maxLength={254}
                placeholder="you@school.edu"
              />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                required
                minLength={8}
                maxLength={128}
                aria-describedby="password-help"
              />
            </label>
            <small id="password-help" className="muted">
              8–128 characters.
            </small>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <button className="full-width" type="submit">
              {busy ? "Please wait…" : register ? "Create account" : "Log in"}
            </button>
          </fieldset>
        </form>
        {(register || config?.allow_public_signup) && (
          <p className="auth-switch">
            {register ? "Already have an account?" : "New to Boardom?"}{" "}
            <Link href={register ? "/login" : "/register"}>
              {register ? "Log in" : "Create an account"}
            </Link>
          </p>
        )}
        {!register && (
          <p className="auth-switch">
            <Link href="/admin-reset">Forgot admin password?</Link>
          </p>
        )}
      </section>
    </div>
  );
}
