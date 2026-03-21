import { TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface PulseLoaderProps {
  size?: "sm" | "md" | "lg";
  label?: string;
  sublabel?: string;
  progress?: number;
  className?: string;
}

const SIZES = {
  sm: { icon: "h-4 w-4", ring: "w-8 h-8", wrapper: "" },
  md: { icon: "h-6 w-6", ring: "w-14 h-14", wrapper: "" },
  lg: { icon: "h-8 w-8", ring: "w-18 h-18", wrapper: "py-10" },
};

export function PulseLoader({
  size = "md",
  label,
  sublabel,
  progress,
  className,
}: PulseLoaderProps) {
  const s = SIZES[size];

  return (
    <div className={cn("flex flex-col items-center", s.wrapper, className)}>
      <div className="relative flex items-center justify-center mb-3">
        <div
          className={cn(
            "absolute rounded-full bg-[#00ccb1]/15 animate-qp-ring",
            s.ring
          )}
        />
        <div className="relative animate-qp-pulse">
          <div
            className={cn(
              "rounded-2xl bg-gradient-to-br from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] flex items-center justify-center",
              size === "sm" ? "w-8 h-8 rounded-lg" : size === "md" ? "w-12 h-12" : "w-16 h-16"
            )}
          >
            <TrendingUp className={cn(s.icon, "text-white")} />
          </div>
        </div>
      </div>

      {label && (
        <div className="text-[15px] font-semibold text-foreground mt-1">
          {label}
        </div>
      )}

      {progress !== undefined && (
        <div className="w-full max-w-xs h-2 bg-muted rounded-full overflow-hidden mt-3">
          <div
            className="h-full rounded-full bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] animate-qp-bar transition-all duration-300"
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </div>
      )}

      {sublabel && (
        <p className="text-[13px] text-foreground/60 mt-2 text-center max-w-md">
          {sublabel}
        </p>
      )}
    </div>
  );
}

export function PulseInline({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 text-foreground/60 text-sm",
        className
      )}
    >
      <span className="w-5 h-5 rounded-md bg-gradient-to-br from-[#00ccb1] to-[#7b61ff] flex items-center justify-center animate-qp-pulse">
        <TrendingUp className="h-3 w-3 text-white" />
      </span>
    </span>
  );
}
