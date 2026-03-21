"use client";

import { cn, formatDollar } from "@/lib/utils";
import { motion } from "framer-motion";
import { Badge } from "./badge";
import { GlowingEffect } from "./ui/glowing-effect";
import type { BadgeVariant } from "@/lib/types";
import type { EntrySignal } from "@/lib/entry-timing";

interface TradeCardStat {
  label: string;
  value: string;
  color?: string;
}

interface TradeCardProps {
  ticker: string;
  name?: string;
  rank?: number;
  badges?: Array<{ text: string; variant: BadgeVariant }>;
  price?: number;
  stats?: TradeCardStat[];
  meta?: string;
  entrySignal?: EntrySignal;
  rightContent?: React.ReactNode;
  className?: string;
  index?: number;
}

const RANK_COLORS: Record<number, string> = {
  1: "#00ccb1",
  2: "#38bdf8",
  3: "#a78bfa",
  4: "#6366f1",
  5: "#94a3b8",
};

const SIGNAL_STYLES: Record<BadgeVariant, { bg: string; border: string; text: string }> = {
  green: { bg: "bg-emerald-500/8", border: "border-emerald-500/20", text: "text-emerald-400" },
  amber: { bg: "bg-amber-500/8", border: "border-amber-500/20", text: "text-amber-400" },
  red: { bg: "bg-rose-500/8", border: "border-rose-500/20", text: "text-rose-400" },
  blue: { bg: "bg-blue-500/8", border: "border-blue-500/20", text: "text-blue-400" },
  purple: { bg: "bg-violet-500/8", border: "border-violet-500/20", text: "text-violet-400" },
  gray: { bg: "bg-muted/50", border: "border-border", text: "text-foreground/80" },
};

const SIGNAL_ICONS: Record<string, string> = {
  green: "↓",
  amber: "↔",
  red: "↑",
};

export function TradeCard({
  ticker,
  name,
  rank,
  badges,
  price,
  stats,
  meta,
  entrySignal,
  rightContent,
  className,
  index = 0,
}: TradeCardProps) {
  return (
    <motion.div
      className={cn(
        "relative rounded-[1.25rem] border-[0.75px] border-border p-2 mb-3 md:rounded-[1.5rem] md:p-3",
        className
      )}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.4,
        delay: index * 0.06,
        ease: [0.25, 0.46, 0.45, 0.94],
      }}
    >
      <GlowingEffect
        spread={40}
        glow
        disabled={false}
        proximity={64}
        inactiveZone={0.01}
        borderWidth={3}
      />
      <div className="relative rounded-xl border-[0.75px] border-border bg-background px-6 py-5 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-3">
            {rank !== undefined && (
              <span
                className="text-xl font-extrabold min-w-[28px]"
                style={{ color: RANK_COLORS[rank] ?? "#94a3b8" }}
              >
                #{rank}
              </span>
            )}
            <span className="text-[17px] font-bold text-foreground">
              {ticker}
            </span>
            {name && (
              <span className="text-[13px] text-foreground/80">{name}</span>
            )}
            {badges?.map((b, i) => (
              <Badge key={i} variant={b.variant}>
                {b.text}
              </Badge>
            ))}
          </div>
          {price !== undefined && (
            <div className="text-xl font-bold text-foreground">
              {formatDollar(price)}
            </div>
          )}
          {rightContent}
        </div>

        {/* Stats row */}
        {stats && stats.length > 0 && (
          <div className="flex gap-6 mt-4 flex-wrap">
            {stats.map((s, i) => (
              <div key={i}>
                <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/80 font-medium">
                  {s.label}
                </div>
                <div
                  className="font-semibold text-[14px] text-foreground mt-0.5"
                  style={s.color ? { color: s.color } : undefined}
                >
                  {s.value}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Entry timing signal */}
        {entrySignal && (
          <div
            className={cn(
              "mt-4 px-4 py-3 rounded-xl border flex items-start gap-3",
              SIGNAL_STYLES[entrySignal.variant].bg,
              SIGNAL_STYLES[entrySignal.variant].border
            )}
          >
            <span
              className={cn(
                "text-lg font-bold leading-none mt-0.5 shrink-0",
                SIGNAL_STYLES[entrySignal.variant].text
              )}
            >
              {SIGNAL_ICONS[entrySignal.variant] ?? "•"}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "text-[13px] font-bold",
                    SIGNAL_STYLES[entrySignal.variant].text
                  )}
                >
                  {entrySignal.label}
                </span>
                {entrySignal.isAI && (
                  <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                    AI
                  </span>
                )}
              </div>
              {entrySignal.simple && (
                <div className="text-[13px] text-foreground mt-1 leading-relaxed">
                  {entrySignal.simple}
                </div>
              )}
              {entrySignal.detail && (
                <div className="text-[12px] text-foreground/80 mt-1 leading-relaxed">
                  {entrySignal.detail}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Meta / reason */}
        {meta && (
          <div className="text-[13px] text-foreground/80 mt-3 leading-relaxed">
            {meta}
          </div>
        )}
      </div>
    </motion.div>
  );
}
