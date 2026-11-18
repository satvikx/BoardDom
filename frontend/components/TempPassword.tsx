"use client";
import { useState } from "react";

export function TempPassword({
  name,
  email,
  password,
  onDismiss,
}: {
  name: string;
  email: string;
  password: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState("");
  async function copy() {
    try {
      await navigator.clipboard.writeText(password);
      setCopied("Copied.");
    } catch {
      setCopied("Copy failed. Select the password and copy it manually.");
    }
  }
  return (
    <div className="temp-password" role="status">
      <h3>Account created for {name}</h3>
      <p>
        <strong>Shown only once.</strong> Give {email} this temporary password
        now. It cannot be shown again; they must change it when they first log
        in.
      </p>
      <div className="copy-row">
        <code aria-label="Temporary password">{password}</code>
        <button type="button" className="secondary" onClick={() => void copy()}>
          Copy
        </button>
      </div>
      {copied && <small>{copied}</small>}
      <button type="button" className="text-button" onClick={onDismiss}>
        I have saved it, hide it
      </button>
    </div>
  );
}
