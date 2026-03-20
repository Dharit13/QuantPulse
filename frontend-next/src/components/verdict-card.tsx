import { cn } from "@/lib/utils";
import { Badge } from "./badge";
import type { BadgeVariant } from "@/lib/types";

type VerdictType = "buy" | "sell" | "avoid" | "wait" | "hold" | "conflict";

const VERDICT_STYLES: Record<VerdictType, string> = {
  buy: "bg-qp-green-bg border-qp-green/20",
  sell: "bg-qp-red-bg border-qp-red/20",
  avoid: "bg-qp-red-bg border-qp-red/20",
  wait: "bg-qp-amber-bg border-qp-amber/20",
  hold: "bg-qp-blue-bg border-qp-blue/20",
  conflict: "bg-qp-amber-bg border-qp-amber/20",
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
        "rounded-2xl border px-7 py-6 transition-all duration-200 hover:shadow-[var(--shadow-card-hover)]",
        VERDICT_STYLES[verdictType],
        className
      )}
    >
      <div className="flex justify-between items-center flex-wrap gap-2">
        <h2 className="text-xl font-bold text-text-primary">{title}</h2>
        {score !== undefined && (
          <Badge variant={scoreVariant} className="text-[14px] px-4 py-1.5">
            Score {score}/100
          </Badge>
        )}
      </div>
      <div className="mt-4">{children}</div>
    </div>
  );
}
