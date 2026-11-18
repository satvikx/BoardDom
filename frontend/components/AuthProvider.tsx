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
import {
  api,
  ApiError,
  errorMessage,
  HOME,
  type PublicConfig,
  type Role,
  type User,
} from "@/lib/api";

type Auth = {
  user: User | null;
  loading: boolean;
  error: string;
  config: PublicConfig | null;
  setUser: (u: User | null) => void;
  reload: () => Promise<void>;
};
const Context = createContext<Auth | null>(null);
const ROLE_NAMES: Record<Role, string> = {
  admin: "administrators",
  teacher: "teachers",
  student: "students",
};
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [config, setConfig] = useState<PublicConfig | null>(null);
  useEffect(() => {
    api<PublicConfig>("/config")
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);
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
    <Context.Provider value={{ user, loading, error, config, setUser, reload }}>
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
      } else if (
        error instanceof ApiError &&
        error.status === 403 &&
        error.message.includes("temporary password")
      ) {
        router.replace("/change-password");
      }
      return errorMessage(error);
    },
    [setUser, router],
  );
}
export function Protected({
  children,
  roles,
  passwordChangePage = false,
}: {
  children: React.ReactNode;
  roles?: Role[];
  passwordChangePage?: boolean;
}) {
  const { user, loading, error, reload } = useAuth();
  const router = useRouter();
  const mustChange = !!user?.must_change_password && !passwordChangePage;
  useEffect(() => {
    if (!loading && !user && !error) router.replace("/login");
    else if (mustChange) router.replace("/change-password");
  }, [user, loading, error, mustChange, router]);
  if (error)
    return (
      <div className="panel">
        <p role="alert">{error}</p>
        <button onClick={() => void reload()}>Retry</button>
      </div>
    );
  if (loading || !user || mustChange)
    return (
      <p role="status" className="loading">
        Loading your workspace…
      </p>
    );
  if (roles && !roles.includes(user.role))
    return (
      <div className="empty-state not-allowed" role="alert">
        <span className="empty-mark" aria-hidden="true">
          ⊘
        </span>
        <h1>Not allowed</h1>
        <p>
          This page is only for {roles.map((r) => ROLE_NAMES[r]).join(" and ")}.
          You are signed in as {user.display_name} ({user.role}).
        </p>
        <Link className="button" href={HOME[user.role]}>
          Go to my home page
        </Link>
      </div>
    );
  return <>{children}</>;
}
function RoleLinks({ user }: { user: User }) {
  if (user.must_change_password) return null;
  return (
    <>
      {user.role === "admin" && (
        <>
          <Link href="/admin">Users</Link>
          <Link href="/admin/evals">Evals</Link>
          <Link href="/admin/efficiency">Efficiency</Link>
        </>
      )}
      {user.role === "teacher" && (
        <>
          <Link href="/dashboard">My workspaces</Link>
          <Link href="/students">Students</Link>
        </>
      )}
      {user.role === "student" && <Link href="/learn">My courses</Link>}
      <Link href="/change-password">Password</Link>
    </>
  );
}
export function Header() {
  const { user, loading, config, setUser } = useAuth();
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
                <span className="role-tag">{user.role}</span>
                <RoleLinks user={user} />
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
                {config?.allow_public_signup && (
                  <Link className="button small" href="/register">
                    Get started
                  </Link>
                )}
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
