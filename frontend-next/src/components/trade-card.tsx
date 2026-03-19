import { cn, formatDollar } from "@/lib/utils";
import { Badge } from "./badge";
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
}

const RANK_COLORS: Record<number, string> = {
  1: "#539616",
  2: "#3b7dd8",
  3: "#c6a339",
  4: "#6c5ce7",
  5: "#6b6b63",
};

const SIGNAL_STYLES: Record<BadgeVariant, { bg: string; border: string; icon: string }> = {
  green: { bg: "bg-qp-green-bg", border: "border-qp-green/20", icon: "text-qp-green" },
  amber: { bg: "bg-qp-amber-bg", border: "border-qp-amber/20", icon: "text-qp-amber" },
  red: { bg: "bg-qp-red-bg", border: "border-qp-red/20", icon: "text-qp-red" },
  blue: { bg: "bg-qp-blue-bg", border: "border-qp-blue/20", icon: "text-qp-blue" },
  purple: { bg: "bg-qp-purple-bg", border: "border-qp-purple/20", icon: "text-qp-purple" },
  gray: { bg: "bg-card-alt", border: "border-border", icon: "text-text-muted" },
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
}: TradeCardProps) {
  return (
    <div
      className={cn(
        "bg-card border border-border rounded-2xl px-6 py-5 mb-3 transition-all duration-150 hover:shadow-[var(--shadow-card-hover)] hover:border-border-hover",
        className
      )}
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          {rank !== undefined && (
            <span
              className="text-xl font-extrabold font-mono min-w-[28px]"
              style={{ color: RANK_COLORS[rank] ?? "#6b6b63" }}
            >
              #{rank}
            </span>
          )}
          <span className="text-[17px] font-bold text-text-primary">
            {ticker}
          </span>
          {name && (
            <span className="text-[13px] text-text-muted">{name}</span>
          )}
          {badges?.map((b, i) => (
            <Badge key={i} variant={b.variant}>
              {b.text}
            </Badge>
          ))}
        </div>
        {price !== undefined && (
          <div className="font-mono text-xl font-bold text-text-primary">
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
              <div className="text-[10px] uppercase tracking-[0.8px] text-text-muted font-medium">
                {s.label}
              </div>
              <div
                className="font-mono font-semibold text-[14px] text-text-primary mt-0.5"
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
              SIGNAL_STYLES[entrySignal.variant].icon
            )}
          >
            {SIGNAL_ICONS[entrySignal.variant] ?? "•"}
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "text-[13px] font-bold",
                  SIGNAL_STYLES[entrySignal.variant].icon
                )}
              >
                {entrySignal.label}
              </span>
              {entrySignal.isAI && (
                <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent/10 text-accent border border-accent/15">
                  AI
                </span>
              )}
            </div>
            {entrySignal.simple && (
              <div className="text-[13px] text-text-primary mt-1 leading-relaxed">
                {entrySignal.simple}
              </div>
            )}
            {entrySignal.detail && (
              <div className="text-[12px] text-text-muted mt-1 leading-relaxed font-mono">
                {entrySignal.detail}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Meta / reason */}
      {meta && (
        <div className="text-[13px] text-text-secondary mt-3 leading-relaxed">
          {meta}
        </div>
      )}
    </div>
  );
}
