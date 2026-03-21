import { cn } from "@/lib/utils";
import type { BadgeVariant } from "@/lib/types";

const VARIANT_STYLES: Record<BadgeVariant, string> = {
  green: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  red: "bg-rose-500/10 text-rose-400 border-rose-500/20",
  amber: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  blue: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  purple: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  gray: "bg-slate-500/10 text-slate-400 border-slate-500/20",
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
        "inline-block px-2.5 py-[3px] rounded-lg text-[11px] font-semibold uppercase tracking-wide border transition-colors duration-150",
        VARIANT_STYLES[variant],
        className
      )}
    >
      {children}
    </span>
  );
}
