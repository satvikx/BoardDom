"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError, errorMessage, type User } from "@/lib/api";

type Auth = {
  user: User | null;
  loading: boolean;
  error: string;
  setUser: (u: User | null) => void;
  reload: () => Promise<void>;
};
const Context = createContext<Auth | null>(null);
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    return api<User>("/auth/me")
      .then((user) => {
        setUser(user);
        setError("");
      })
      .catch((e) => {
        setUser(null);
        setError(
          e instanceof ApiError && e.status === 401 ? "" : errorMessage(e),
        );
      })
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);
  return (
    <Context.Provider value={{ user, loading, error, setUser, reload }}>
      {children}
    </Context.Provider>
  );
}
export function useAuth() {
  const auth = useContext(Context);
  if (!auth) throw new Error("AuthProvider is required");
  return auth;
}
export function useRequestError() {
  const { setUser } = useAuth();
  const router = useRouter();
  return useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        setUser(null);
        router.replace("/login?expired=1");
      }
      return errorMessage(error);
    },
    [setUser, router],
  );
}
export function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading, error, reload } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !user && !error) router.replace("/login");
  }, [user, loading, error, router]);
  if (error)
    return (
      <div className="panel">
        <p role="alert">{error}</p>
        <button onClick={() => void reload()}>Retry</button>
      </div>
    );
  if (loading || !user)
    return (
      <p role="status" className="loading">
        Loading your workspace…
      </p>
    );
  return <>{children}</>;
}
export function Header() {
  const { user, loading, setUser } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function logout() {
    setBusy(true);
    setError("");
    try {
      await api<void>("/auth/logout", { method: "POST" });
      setUser(null);
      router.push("/login");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <header className="site-header">
      <div className="header-inner">
        <Link className="brand" href="/" aria-label="Boardom home">
          <span className="brand-mark" aria-hidden="true">
            b.
          </span>
          Boardom
        </Link>
        <nav aria-label="Main navigation">
          {!loading &&
            (user ? (
              <>
                <Link href="/dashboard">My workspaces</Link>
                <button
                  className="text-button"
                  disabled={busy}
                  onClick={logout}
                >
                  {busy ? "Logging out…" : "Log out"}
                </button>
              </>
            ) : (
              <>
                <Link href="/login">Log in</Link>
                <Link className="button small" href="/register">
                  Get started
                </Link>
              </>
            ))}
        </nav>
        {error && (
          <p className="error header-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </header>
  );
}
