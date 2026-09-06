"use client";

// Sign in / create account. Onboarding continues on the watchlists screen.

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui";

export default function LoginPage() {
  const { user, loading, login, register } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [user, loading, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, displayName || email.split("@")[0]);
      router.replace("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <h1 className="text-[22px] font-semibold tracking-tight text-ink">
            Since You Last Looked
          </h1>
          <p className="mt-2 text-[13px] leading-relaxed text-muted">
            A watchlist that remembers what you have already seen, and tells you what
            meaningfully changed while you were away.
          </p>
        </div>

        <div
          role="tablist"
          aria-label="Sign in or create an account"
          className="mb-5 inline-flex rounded-md border border-line bg-surface p-0.5"
        >
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => {
                setMode(m);
                setError(null);
              }}
              className={`rounded px-3 py-1.5 text-[13px] transition-colors ${
                mode === m ? "bg-surface-2 font-medium text-ink" : "text-muted hover:text-ink"
              }`}
            >
              {m === "login" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-3.5">
          {mode === "register" ? (
            <div>
              <label htmlFor="name" className="mb-1 block text-[12px] font-medium text-ink-2">
                Name
              </label>
              <input
                id="name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="name"
                className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-faint"
                placeholder="Your name"
              />
            </div>
          ) : null}

          <div>
            <label htmlFor="email" className="mb-1 block text-[12px] font-medium text-ink-2">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-faint"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1 block text-[12px] font-medium text-ink-2">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={mode === "register" ? 8 : 1}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-faint"
              placeholder={mode === "register" ? "At least 8 characters" : "Your password"}
            />
          </div>

          {error ? (
            <p role="alert" className="rounded-md bg-down-soft px-3 py-2 text-[13px] text-down">
              {error}
            </p>
          ) : null}

          <Button type="submit" disabled={busy} className="w-full">
            {busy
              ? "Please wait…"
              : mode === "login"
                ? "Sign in"
                : "Create account"}
          </Button>
        </form>

        <p className="mt-5 text-[12px] leading-relaxed text-faint">
          Your watchlists, last-viewed times and reviewed state are stored on the server, so
          signing in from another device restores exactly where you left off.
        </p>
      </div>
    </div>
  );
}
