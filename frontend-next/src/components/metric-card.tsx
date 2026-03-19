import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: string;
  delta?: string;
  deltaColor?: "green" | "red" | "neutral";
  valueColor?: string;
  className?: string;
}

export function MetricCard({
  label,
  value,
  delta,
  deltaColor = "neutral",
  valueColor,
  className,
}: MetricCardProps) {
  const deltaStyles = {
    green: "text-qp-green",
    red: "text-qp-red",
    neutral: "text-text-muted",
  };

  return (
    <div
      className={cn(
        "bg-card rounded-2xl px-5 py-4 border border-border",
        className
      )}
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="text-[12px] text-text-muted font-medium mb-1">
        {label}
      </div>
      <div
        className="font-mono font-bold text-2xl tracking-tight"
        style={{ color: valueColor || undefined }}
      >
        {!valueColor && <span className="text-text-primary">{value}</span>}
        {valueColor && value}
      </div>
      {delta && (
        <div
          className={cn("text-[12px] font-medium mt-1", deltaStyles[deltaColor])}
        >
          {delta}
        </div>
      )}
    </div>
  );
}
