"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Search,
  Radio,
  Zap,
  TrendingUp,
  Lightbulb,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { checkHealth, apiGet } from "@/lib/api";
import type { RegimeData } from "@/lib/types";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/stock-analysis", label: "Stock Analysis", icon: Search },
  { href: "/invest", label: "AI Research", icon: Lightbulb },
  { href: "/scanner", label: "Scanner", icon: Radio },
  { href: "/swing-picks", label: "Swing Picks", icon: Zap },
] as const;

const REGIME_COLORS: Record<string, string> = {
  bull_trend: "#2d9d3a",
  bull_choppy: "#539616",
  bear_trend: "#c68a1a",
  crisis: "#d44040",
  mean_reverting: "#6c5ce7",
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
    return { label: "Closed", color: "#d44040", time };
  if (t < 240) return { label: "Closed", color: "#d44040", time };
  if (t < 570) return { label: "Pre-Market", color: "#c68a1a", time };
  if (t < 960) return { label: "Open", color: "#2d9d3a", time };
  if (t < 1200) return { label: "After-Hours", color: "#6c5ce7", time };
  return { label: "Closed", color: "#d44040", time };
}

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [regime, setRegime] = useState<RegimeData | null>(null);
  const [marketStatus, setMarketStatus] = useState(getMarketStatus);

  useEffect(() => {
    checkHealth().then(setHealthy);
    apiGet<RegimeData>("/regime/current").then(setRegime);
    const interval = setInterval(() => setMarketStatus(getMarketStatus()), 30_000);
    return () => clearInterval(interval);
  }, []);

  const regimeName =
    regime?.regime
      ?.replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase()) ?? "";
  const regimeColor = REGIME_COLORS[regime?.regime ?? ""] ?? "#3b7dd8";
  const now = new Date();

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 h-screen z-50 flex flex-col bg-card border-r border-border transition-all duration-200",
        collapsed ? "w-[72px]" : "w-[250px]"
      )}
      style={{ boxShadow: "var(--shadow-sidebar)" }}
    >
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 pt-6 pb-4">
        <div className="w-9 h-9 rounded-xl bg-accent flex items-center justify-center shrink-0">
          <TrendingUp className="h-5 w-5 text-white" />
        </div>
        {!collapsed && (
          <div>
            <div className="text-[17px] font-bold text-text-primary tracking-tight leading-tight">
              QuantPulse
            </div>
            <div className="text-[11px] text-text-secondary font-medium">
              Trading Advisory
            </div>
          </div>
        )}
      </div>

      {/* Status bar */}
      <div className="mx-4 mb-3 px-3 py-2.5 rounded-xl bg-card-alt border border-border">
        <div className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{
              background: healthy ? "#2d9d3a" : healthy === false ? "#d44040" : "#a6a6a0",
              boxShadow: healthy ? "0 0 6px rgba(45,157,58,0.4)" : "none",
            }}
          />
          {!collapsed && (
            <span className="text-[12px] text-text-secondary">
              {healthy === null ? "Checking..." : healthy ? "API Connected" : "API Offline"}
            </span>
          )}
        </div>
        {!collapsed && (
          <div className="flex items-center gap-2 mt-1.5">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{
                background: marketStatus.color,
                boxShadow: `0 0 6px ${marketStatus.color}40`,
              }}
            />
            <span className="text-[12px]">
              <span className="font-medium text-text-primary">
                {marketStatus.label}
              </span>{" "}
              <span className="text-text-secondary">{marketStatus.time}</span>
            </span>
          </div>
        )}
        {regime && !collapsed && (
          <div className="flex items-center gap-2 mt-1.5">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{ background: regimeColor }}
            />
            <span className="text-[12px] font-medium text-text-primary">
              {regimeName}
            </span>
            <span className="text-[11px] text-text-secondary">
              {Math.round(regime.confidence * 100)}%
            </span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 flex flex-col gap-1 px-3 py-1">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-xl text-[14px] transition-all duration-150 cursor-pointer active:scale-[0.98]",
                active
                  ? "bg-accent text-white font-semibold shadow-sm"
                  : "text-text-body hover:bg-card-alt hover:text-text-primary"
              )}
              title={collapsed ? label : undefined}
            >
              <Icon className="h-[18px] w-[18px] shrink-0" />
              {!collapsed && <span>{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 pb-4 pt-2">
        {!collapsed && (
          <div className="text-text-secondary text-[11px] leading-relaxed mb-2">
            <div>
              {now.toLocaleDateString("en-US", {
                weekday: "short",
                month: "short",
                day: "numeric",
              })}
            </div>
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center justify-center w-full py-2 rounded-xl text-text-secondary hover:text-text-primary hover:bg-card-alt transition-colors cursor-pointer"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </button>
      </div>
    </aside>
  );
}
