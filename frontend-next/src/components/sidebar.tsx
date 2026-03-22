"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  LayoutDashboard,
  Search,
  Radio,
  Zap,
  TrendingUp,
  Lightbulb,
  Newspaper,
  ScanEye,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  Sun,
  Moon,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { checkHealth, apiGet } from "@/lib/api";
import { useTheme } from "@/components/theme-provider";
import { getSupabase } from "@/lib/supabase";
import { GlowingEffect } from "./ui/glowing-effect";
import type { RegimeData } from "@/lib/types";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/stock-analysis", label: "Stock Analysis", icon: Search },
  { href: "/invest", label: "AI Research", icon: Lightbulb },
  { href: "/scanner", label: "Scanner", icon: Radio },
  { href: "/swing-picks", label: "Swing Picks", icon: Zap },
  { href: "/overnight", label: "Overnight AI", icon: ScanEye },
  { href: "/news", label: "News", icon: Newspaper },
] as const;

const REGIME_COLORS: Record<string, string> = {
  bull_trend: "#34d399",
  bull_choppy: "#34d399",
  bear_trend: "#fbbf24",
  crisis: "#fb7185",
  mean_reverting: "#a78bfa",
};

function getMarketStatus(): { label: string; color: string; time: string } {
  const et = new Date(
    new Date().toLocaleString("en-US", { timeZone: "America/New_York" })
  );
  const weekday = et.getDay();
  const h = et.getHours();
  const m = et.getMinutes();
  const t = h * 60 + m;
  const time = et.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
    timeZoneName: "short",
  });

  if (weekday === 0 || weekday === 6)
    return { label: "Closed", color: "#fb7185", time };
  if (t < 240) return { label: "Closed", color: "#fb7185", time };
  if (t < 570) return { label: "Pre-Market", color: "#fbbf24", time };
  if (t < 960) return { label: "Open", color: "#34d399", time };
  if (t < 1200) return { label: "After-Hours", color: "#a78bfa", time };
  return { label: "Closed", color: "#fb7185", time };
}

export function Sidebar() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [regime, setRegime] = useState<RegimeData | null>(null);
  const [marketStatus, setMarketStatus] = useState(getMarketStatus);

  useEffect(() => {
    checkHealth().then(setHealthy);
    apiGet<RegimeData>("/regime/current").then(setRegime);
    const interval = setInterval(
      () => setMarketStatus(getMarketStatus()),
      30_000
    );
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const regimeName =
    regime?.regime
      ?.replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase()) ?? "";
  const regimeColor = REGIME_COLORS[regime?.regime ?? ""] ?? "#38bdf8";
  const now = new Date();

  const showLabels = mobileOpen || !collapsed;

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed top-4 left-4 z-30 md:hidden flex items-center justify-center w-10 h-10 rounded-xl bg-background border border-border cursor-pointer hover:bg-muted transition-colors"
        aria-label="Open navigation"
      >
        <Menu className="h-5 w-5 text-foreground" />
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        className={cn(
          "fixed left-0 top-0 h-screen z-30 flex flex-col bg-background transition-all duration-200 overflow-hidden",
          mobileOpen
            ? "w-[250px] translate-x-0"
            : "max-md:-translate-x-full",
          !mobileOpen && (collapsed ? "md:w-[72px]" : "md:w-[250px]")
        )}
      >
        {/* Gradient right edge */}
        <div
          className="absolute -right-[1px] top-0 bottom-0 w-[2px] opacity-40"
          style={{
            background: "linear-gradient(180deg, #dd7bbb, #d79f1e, #5a922c, #4c7894, #dd7bbb)",
            backgroundSize: "100% 200%",
            animation: "gradient-rotate 3s linear infinite",
          }}
        />

        {/* Mobile close button */}
        <button
          onClick={() => setMobileOpen(false)}
          className="absolute top-4 right-3 md:hidden flex items-center justify-center w-8 h-8 rounded-lg hover:bg-muted transition-colors cursor-pointer"
          aria-label="Close navigation"
        >
          <X className="h-4 w-4 text-foreground/80" />
        </button>

        {/* Logo */}
        <div className="flex items-center gap-2.5 px-5 pt-6 pb-4">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] flex items-center justify-center shrink-0">
            <TrendingUp className="h-5 w-5 text-white" />
          </div>
          {showLabels && (
            <div>
              <div className="text-[17px] font-black tracking-tight leading-tight">
                <span className="bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] bg-clip-text text-transparent">
                  QuantPulse
                </span>
              </div>
              <div className="text-[11px] text-foreground font-medium">
                Trading Advisory
              </div>
            </div>
          )}
        </div>

        {/* Status bar */}
        <div className="relative mx-3 mb-3 rounded-[1rem] border-[0.75px] border-border p-1.5">
          <GlowingEffect
            spread={40}
            glow
            disabled={false}
            proximity={64}
            inactiveZone={0.01}
            borderWidth={2}
          />
          <div className="relative rounded-[0.625rem] border-[0.75px] border-border bg-background px-3 py-2.5 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
            <div className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{
                  background: healthy
                    ? "#34d399"
                    : healthy === false
                      ? "#fb7185"
                      : "#94a3b8",
                  boxShadow: healthy ? "0 0 6px rgba(52,211,153,0.4)" : "none",
                }}
              />
              {showLabels && (
                <span className="text-[12px] text-foreground/80">
                  {healthy === null
                    ? "Checking..."
                    : healthy
                      ? "API Connected"
                      : "API Offline"}
                </span>
              )}
            </div>
            {showLabels && (
              <div className="flex items-center gap-2 mt-1.5">
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{
                    background: marketStatus.color,
                    boxShadow: `0 0 6px ${marketStatus.color}40`,
                  }}
                />
                <span className="text-[12px]">
                  <span className="font-medium text-foreground">
                    {marketStatus.label}
                  </span>{" "}
                  <span className="text-foreground/80">{marketStatus.time}</span>
                </span>
              </div>
            )}
            {regime && showLabels && (
              <div className="flex items-center gap-2 mt-1.5">
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ background: regimeColor }}
                />
                <span className="text-[12px] font-medium text-foreground">
                  {regimeName}
                </span>
                <span className="text-[11px] text-foreground/80">
                  {Math.round(regime.confidence * 100)}%
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 flex flex-col gap-1 px-3 py-1">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <div key={href} className="relative rounded-[1rem] border-[0.75px] border-border p-[3px]">
                <GlowingEffect
                  spread={40}
                  glow
                  disabled={false}
                  proximity={64}
                  inactiveZone={0.01}
                  borderWidth={2}
                />
                <Link
                  href={href}
                  className={cn(
                    "relative flex items-center gap-3 px-3 py-2 rounded-[0.75rem] border-[0.75px] border-border bg-background text-[14px] cursor-pointer active:scale-[0.98] shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)] transition-colors",
                    active
                      ? "text-foreground font-semibold"
                      : "text-foreground hover:text-foreground"
                  )}
                  title={!showLabels ? label : undefined}
                >
                  <Icon className="h-[18px] w-[18px] shrink-0" />
                  {showLabels && <span>{label}</span>}
                </Link>
              </div>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="px-3 pb-4 pt-2 space-y-2">
          {showLabels && (
            <div className="text-center text-foreground text-[12px] font-medium">
              {now.toLocaleDateString("en-US", {
                weekday: "short",
                month: "short",
                day: "numeric",
              })}
            </div>
          )}

          {/* Sign out */}
          {process.env.NEXT_PUBLIC_AUTH_ENABLED === "true" && (
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
                onClick={async () => {
                  const client = getSupabase();
                  if (client) await client.auth.signOut();
                }}
                className={cn(
                  "relative flex items-center gap-3 w-full px-3 py-2 rounded-[0.75rem] border-[0.75px] border-border bg-background text-foreground/70 hover:text-destructive text-[14px] cursor-pointer active:scale-[0.98] shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)] transition-colors",
                  !showLabels && "justify-center"
                )}
                aria-label="Sign out"
              >
                <LogOut className="h-[18px] w-[18px] shrink-0" />
                {showLabels && <span>Sign Out</span>}
              </button>
            </div>
          )}

          {/* Theme toggle */}
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
              onClick={toggleTheme}
              className={cn(
                "relative flex items-center gap-3 w-full px-3 py-2 rounded-[0.75rem] border-[0.75px] border-border bg-background text-foreground hover:text-foreground text-[14px] cursor-pointer active:scale-[0.98] shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)] transition-colors",
                !showLabels && "justify-center"
              )}
              aria-label={
                theme === "dark"
                  ? "Switch to light mode"
                  : "Switch to dark mode"
              }
            >
              {theme === "dark" ? (
                <Sun className="h-[18px] w-[18px] shrink-0" />
              ) : (
                <Moon className="h-[18px] w-[18px] shrink-0" />
              )}
              {showLabels && (
                <span className="text-[14px]">
                  {theme === "dark" ? "Light Mode" : "Dark Mode"}
                </span>
              )}
            </button>
          </div>

          {/* Collapse toggle (desktop only) */}
          <div className="hidden md:block relative rounded-[1rem] border-[0.75px] border-border p-[3px]">
            <GlowingEffect
              spread={40}
              glow
              disabled={false}
              proximity={64}
              inactiveZone={0.01}
              borderWidth={2}
            />
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="relative flex items-center justify-center w-full py-2 rounded-[0.75rem] border-[0.75px] border-border bg-background text-foreground/70 hover:text-foreground cursor-pointer active:scale-[0.98] shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)] transition-colors"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {collapsed ? (
                <ChevronRight className="h-[18px] w-[18px]" />
              ) : (
                <ChevronLeft className="h-[18px] w-[18px]" />
              )}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
