"use client";

import { useState, useEffect } from "react";
import { GlowingEffect } from "./ui/glowing-effect";
import { apiGet, apiPost } from "@/lib/api";
import type { RegimeData } from "@/lib/types";

type Session = "open" | "premarket" | "afterhours" | "closed";

interface SessionInfo {
  session: Session;
  time: string;
  dayOfWeek: string;
  color: string;
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
    return { session: "closed", time, dayOfWeek, color: "#fb7185", label: "Weekend" };
  if (t < 240)
    return { session: "closed", time, dayOfWeek, color: "#fb7185", label: "Closed" };
  if (t < 570)
    return { session: "premarket", time, dayOfWeek, color: "#fbbf24", label: "Pre-Market" };
  if (t < 960)
    return { session: "open", time, dayOfWeek, color: "#34d399", label: "Market Open" };
  if (t < 1200)
    return { session: "afterhours", time, dayOfWeek, color: "#a78bfa", label: "After Hours" };
  return { session: "closed", time, dayOfWeek, color: "#fb7185", label: "Closed" };
}

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
    <div className="relative rounded-[1.25rem] border-[0.75px] border-border p-2 md:p-3 mb-6 md:rounded-[1.5rem]">
      <GlowingEffect
        spread={40}
        glow
        disabled={false}
        proximity={64}
        inactiveZone={0.01}
        borderWidth={3}
      />
      <div className="relative rounded-xl border-[0.75px] border-border bg-background py-3.5 flex items-center shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
        <div className="flex items-center gap-3 px-5 shrink-0 border-r border-border pr-5">
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{
              background: info.color,
              boxShadow: `0 0 8px ${info.color}80`,
            }}
          />
          <span className="text-[13px] font-semibold text-foreground whitespace-nowrap">
            {info.label} · {info.time} ET
          </span>
        </div>
        <div className="overflow-hidden flex-1 ml-1">
          {tip ? (
            <div className="animate-marquee whitespace-nowrap flex">
              {[0, 1].map((i) => (
                <span key={i} className="text-[13px] text-foreground/90 shrink-0 px-4">
                  {tip}
                </span>
              ))}
            </div>
          ) : loading ? (
            <span className="text-[13px] text-foreground/80 px-4">Loading market insight...</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
