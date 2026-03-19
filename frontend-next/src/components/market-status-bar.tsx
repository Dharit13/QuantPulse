"use client";

import { useState, useEffect } from "react";
import { apiGet, apiPost } from "@/lib/api";
import type { RegimeData } from "@/lib/types";

type Session = "open" | "premarket" | "afterhours" | "closed";

interface SessionInfo {
  session: Session;
  time: string;
  dayOfWeek: string;
  color: string;
  bgClass: string;
  label: string;
}

function getSessionInfo(): SessionInfo {
  const et = new Date(
    new Date().toLocaleString("en-US", { timeZone: "America/New_York" })
  );
  const weekday = et.getDay();
  const t = et.getHours() * 60 + et.getMinutes();
  const time = et.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  });
  const dayOfWeek = et.toLocaleDateString("en-US", { weekday: "long", timeZone: "America/New_York" });

  if (weekday === 0 || weekday === 6)
    return { session: "closed", time, dayOfWeek, color: "#d44040", bgClass: "bg-qp-red-bg", label: "Weekend" };
  if (t < 240)
    return { session: "closed", time, dayOfWeek, color: "#d44040", bgClass: "bg-qp-red-bg", label: "Closed" };
  if (t < 570)
    return { session: "premarket", time, dayOfWeek, color: "#c68a1a", bgClass: "bg-qp-amber-bg", label: "Pre-Market" };
  if (t < 960)
    return { session: "open", time, dayOfWeek, color: "#2d9d3a", bgClass: "bg-qp-green-bg", label: "Market Open" };
  if (t < 1200)
    return { session: "afterhours", time, dayOfWeek, color: "#6c5ce7", bgClass: "bg-accent-bg", label: "After Hours" };
  return { session: "closed", time, dayOfWeek, color: "#d44040", bgClass: "bg-qp-red-bg", label: "Closed" };
}

// Module-level cache so the AI tip survives navigation
let _cachedTip: string | null = null;
let _cachedSession: Session | null = null;

export function MarketStatusBar() {
  const [info, setInfo] = useState<SessionInfo>(getSessionInfo);
  const [tip, setTip] = useState<string | null>(_cachedTip);
  const [loading, setLoading] = useState(!_cachedTip);

  useEffect(() => {
    const id = setInterval(() => setInfo(getSessionInfo()), 30_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (_cachedTip && _cachedSession === info.session) {
      setTip(_cachedTip);
      setLoading(false);
      return;
    }

    setLoading(true);
    (async () => {
      const regime = await apiGet<RegimeData>("/regime/current");
      const res = await apiPost<{ result: { tip: string } | null }>(
        "/ai/summarize",
        {
          type: "market_timing",
          data: {
            session: info.session,
            time_et: info.time,
            day_of_week: info.dayOfWeek,
            regime: regime?.regime ?? "unknown",
            vix: regime?.vix ?? 0,
            breadth_pct: regime?.breadth_pct ?? 0,
          },
        }
      );
      const aiTip = res?.result?.tip ?? null;
      if (aiTip) {
        _cachedTip = aiTip;
        _cachedSession = info.session;
        setTip(aiTip);
      }
      setLoading(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info.session]);

  return (
    <div
      className={`${info.bgClass} rounded-xl px-4 py-2 mb-6 flex items-center gap-3`}
    >
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{
          background: info.color,
          boxShadow: `0 0 6px ${info.color}50`,
        }}
      />
      <span className="text-[12px] text-text-body leading-relaxed">
        <span className="font-semibold text-text-primary">
          {info.label} · {info.time} ET
        </span>
        {tip && <> · {tip}</>}
        {loading && !tip && (
          <span className="text-text-muted"> · Loading market insight...</span>
        )}
      </span>
    </div>
  );
}
