"use client";

import { useEffect, useState, type ReactNode } from "react";
import { TrendingUp } from "lucide-react";
import { getSupabase } from "@/lib/supabase";
import { GlowingEffect } from "@/components/ui/glowing-effect";
import type { Session } from "@supabase/supabase-js";

const AUTH_ENABLED = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

function GitHubIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
    </svg>
  );
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(AUTH_ENABLED);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [error, setError] = useState("");
  const [oauthLoading, setOauthLoading] = useState(false);

  useEffect(() => {
    if (!AUTH_ENABLED) return;

    const client = getSupabase();
    if (!client) {
      setLoading(false);
      return;
    }

    client.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = client.auth.onAuthStateChange((_event, session) => {
      setSession(session);
    });

    return () => subscription.unsubscribe();
  }, []);

  if (!AUTH_ENABLED) return <>{children}</>;
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-qp-pulse flex flex-col items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] flex items-center justify-center">
            <TrendingUp className="h-5 w-5 text-white" />
          </div>
          <span className="text-sm text-muted-foreground">Loading...</span>
        </div>
      </div>
    );
  }

  if (session) return <>{children}</>;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    const client = getSupabase();
    if (!client) {
      setError("Supabase not configured");
      return;
    }

    if (isSignUp) {
      const { error } = await client.auth.signUp({ email, password });
      if (error) setError(error.message);
    } else {
      const { error } = await client.auth.signInWithPassword({
        email,
        password,
      });
      if (error) setError(error.message);
    }
  };

  const handleGitHubLogin = async () => {
    setError("");
    setOauthLoading(true);

    const client = getSupabase();
    if (!client) {
      setError("Supabase not configured");
      setOauthLoading(false);
      return;
    }

    const { error } = await client.auth.signInWithOAuth({
      provider: "github",
    });

    if (error) {
      setError(error.message);
      setOauthLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-[420px] animate-qp-slide-up">
        {/* Logo + Branding */}
        <div className="flex flex-col items-center gap-3 mb-8">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] flex items-center justify-center shadow-lg">
            <TrendingUp className="h-6 w-6 text-white" />
          </div>
          <div className="text-center">
            <h1 className="text-[22px] font-black tracking-tight">
              <span className="bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] bg-clip-text text-transparent">
                QuantPulse
              </span>
            </h1>
            <p className="text-[13px] text-muted-foreground mt-1">
              {isSignUp ? "Create your account" : "Sign in to your trading advisory"}
            </p>
          </div>
        </div>

        {/* Card */}
        <div className="relative rounded-[1rem] border-[0.75px] border-border p-1.5">
          <GlowingEffect
            spread={40}
            glow
            disabled={false}
            proximity={64}
            inactiveZone={0.01}
            borderWidth={2}
          />
          <div className="relative rounded-[0.625rem] border-[0.75px] border-border bg-background p-6 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
            {/* GitHub OAuth */}
            <div className="relative rounded-[1rem] border-[0.75px] border-border p-[3px]">
              <GlowingEffect
                spread={40}
                glow
                disabled={false}
                proximity={64}
                inactiveZone={0.01}
                borderWidth={2}
              />
              <button
                type="button"
                onClick={handleGitHubLogin}
                disabled={oauthLoading}
                className="relative w-full flex items-center justify-center gap-2.5 rounded-[0.75rem] border-[0.75px] border-border bg-background px-4 py-2.5 text-sm font-medium text-foreground hover:bg-muted cursor-pointer active:scale-[0.98] shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)] transition-colors disabled:opacity-50"
              >
                <GitHubIcon />
                {oauthLoading ? "Redirecting..." : "Continue with GitHub"}
              </button>
            </div>

            {/* Divider */}
            <div className="relative my-5">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-border" />
              </div>
              <div className="relative flex justify-center text-[11px] uppercase tracking-wider">
                <span className="bg-background px-3 text-muted-foreground">
                  or continue with email
                </span>
              </div>
            </div>

            {/* Email/Password Form */}
            <form onSubmit={handleSubmit} className="space-y-3">
              <div className="relative rounded-[1rem] border-[0.75px] border-border p-[3px]">
                <GlowingEffect
                  spread={40}
                  glow
                  disabled={false}
                  proximity={64}
                  inactiveZone={0.01}
                  borderWidth={2}
                />
                <input
                  type="email"
                  placeholder="Email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="relative w-full rounded-[0.75rem] border-[0.75px] border-border bg-background px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-ring shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)] transition-shadow"
                  required
                />
              </div>
              <div className="relative rounded-[1rem] border-[0.75px] border-border p-[3px]">
                <GlowingEffect
                  spread={40}
                  glow
                  disabled={false}
                  proximity={64}
                  inactiveZone={0.01}
                  borderWidth={2}
                />
                <input
                  type="password"
                  placeholder="Password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="relative w-full rounded-[0.75rem] border-[0.75px] border-border bg-background px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-ring shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)] transition-shadow"
                  required
                  minLength={6}
                />
              </div>

              {error && (
                <p className="text-sm text-destructive px-1">{error}</p>
              )}

              <div className="relative rounded-[1rem] border-[0.75px] border-border p-[3px]">
                <GlowingEffect
                  spread={40}
                  glow
                  disabled={false}
                  proximity={64}
                  inactiveZone={0.01}
                  borderWidth={2}
                />
                <button
                  type="submit"
                  className="relative w-full rounded-[0.75rem] bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90 cursor-pointer active:scale-[0.98] transition-all"
                >
                  {isSignUp ? "Create Account" : "Sign In"}
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* Toggle sign-up / sign-in */}
        <p className="text-center text-[13px] text-muted-foreground mt-5">
          {isSignUp ? "Already have an account?" : "Don't have an account?"}{" "}
          <button
            onClick={() => {
              setIsSignUp(!isSignUp);
              setError("");
            }}
            className="bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] bg-clip-text text-transparent font-medium hover:underline cursor-pointer"
          >
            {isSignUp ? "Sign in" : "Sign up"}
          </button>
        </p>
      </div>
    </div>
  );
}
