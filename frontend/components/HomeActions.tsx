"use client";
import Link from "next/link";
import { homeFor } from "@/lib/api";
import { useAuth } from "./AuthProvider";

export function HomeActions() {
  const { user, config } = useAuth();
  if (user)
    return (
      <div className="hero-actions">
        <Link href={homeFor(user)} className="button">
          Continue to Boardom <span aria-hidden="true">↗</span>
        </Link>
      </div>
    );
  return (
    <div className="hero-actions">
      {config?.allow_public_signup ? (
        <>
          <Link href="/register" className="button">
            Create your workspace <span aria-hidden="true">↗</span>
          </Link>
          <Link href="/login">Already here? Log in →</Link>
        </>
      ) : (
        <Link href="/login" className="button">
          Log in <span aria-hidden="true">↗</span>
        </Link>
      )}
    </div>
  );
}
