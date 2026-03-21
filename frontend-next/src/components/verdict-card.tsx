"use client";

import { cn } from "@/lib/utils";
import { Badge } from "./badge";
import { GlowingEffect } from "./ui/glowing-effect";
import type { BadgeVariant } from "@/lib/types";

type VerdictType = "buy" | "sell" | "avoid" | "wait" | "hold" | "conflict";

const VERDICT_STYLES: Record<VerdictType, string> = {
  buy: "bg-emerald-500/5 border-emerald-500/20",
  sell: "bg-rose-500/5 border-rose-500/20",
  avoid: "bg-rose-500/5 border-rose-500/20",
  wait: "bg-amber-500/5 border-amber-500/20",
  hold: "bg-blue-500/5 border-blue-500/20",
  conflict: "bg-amber-500/5 border-amber-500/20",
};

interface VerdictCardProps {
  title: string;
  verdictType: VerdictType;
  score?: number;
  children: React.ReactNode;
  className?: string;
}

export function VerdictCard({
  title,
  verdictType,
  score,
  children,
  className,
}: VerdictCardProps) {
  const scoreVariant: BadgeVariant =
    score !== undefined
      ? score >= 70
        ? "green"
        : score >= 50
          ? "amber"
          : "red"
      : "blue";

  return (
    <div
      className={cn(
        "relative rounded-[1.25rem] border-[0.75px] border-border p-2 md:rounded-[1.5rem] md:p-3",
        className
      )}
    >
      <GlowingEffect
        spread={40}
        glow
        disabled={false}
        proximity={64}
        inactiveZone={0.01}
        borderWidth={3}
      />
      <div
        className={cn(
          "relative rounded-xl border px-7 py-6 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]",
          VERDICT_STYLES[verdictType]
        )}
      >
        <div className="flex justify-between items-center flex-wrap gap-2">
          <h2 className="text-xl font-bold text-foreground">{title}</h2>
          {score !== undefined && (
            <Badge variant={scoreVariant} className="text-[14px] px-4 py-1.5">
              Score {score}/100
            </Badge>
          )}
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}
