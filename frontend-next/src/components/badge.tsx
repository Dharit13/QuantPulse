import { cn } from "@/lib/utils";
import type { BadgeVariant } from "@/lib/types";

const VARIANT_STYLES: Record<BadgeVariant, string> = {
  green: "bg-qp-green-bg text-qp-green border-qp-green/15",
  red: "bg-qp-red-bg text-qp-red border-qp-red/15",
  amber: "bg-qp-amber-bg text-qp-amber border-qp-amber/15",
  blue: "bg-qp-blue-bg text-qp-blue border-qp-blue/15",
  purple: "bg-qp-purple-bg text-qp-purple border-qp-purple/15",
  gray: "bg-[rgba(107,107,99,0.06)] text-text-secondary border-border",
};

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

export function Badge({ children, variant = "blue", className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-block px-2.5 py-[3px] rounded-lg text-[11px] font-semibold uppercase tracking-wide border",
        VARIANT_STYLES[variant],
        className
      )}
    >
      {children}
    </span>
  );
}
