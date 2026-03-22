import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
  variant?: "text" | "card" | "chart" | "circle";
  style?: React.CSSProperties;
}

export function Skeleton({ className, variant = "text", style }: SkeletonProps) {
  const base = "animate-pulse bg-border/60 rounded";
  const variants = {
    text: "h-3 rounded-md",
    card: "rounded-2xl",
    chart: "rounded-2xl",
    circle: "rounded-full",
  };

  return <div className={cn(base, variants[variant], className)} style={style} />;
}

export function MetricCardSkeleton() {
  return (
    <div
      className="bg-background border-[0.75px] border-border rounded-2xl px-5 py-4 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]"
    >
      <Skeleton className="h-3 w-16 mb-3" />
      <Skeleton className="h-7 w-24 mb-2" />
      <Skeleton className="h-3 w-32" />
    </div>
  );
}

export function TradeCardSkeleton() {
  return (
    <div
      className="bg-background border-[0.75px] border-border rounded-2xl px-6 py-5 mb-3 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]"
    >
      <div className="flex items-center gap-3 mb-4">
        <Skeleton className="h-6 w-8" />
        <Skeleton className="h-5 w-16" />
        <Skeleton className="h-5 w-20 rounded-full" variant="text" />
      </div>
      <div className="flex gap-6">
        {[1, 2, 3, 4].map((i) => (
          <div key={i}>
            <Skeleton className="h-2.5 w-10 mb-1.5" />
            <Skeleton className="h-4 w-14" />
          </div>
        ))}
      </div>
      <Skeleton className="h-16 w-full mt-4 rounded-xl" variant="card" />
    </div>
  );
}

const CHART_BAR_HEIGHTS = [
  45, 72, 33, 58, 80, 27, 65, 50, 38, 75, 42, 68,
  55, 30, 78, 48, 62, 35, 70, 52, 40, 74, 56, 28,
];

export function ChartSkeleton({ height = 320 }: { height?: number }) {
  return (
    <div
      className="bg-background border-[0.75px] border-border rounded-2xl overflow-hidden shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]"
      style={{ height }}
    >
      <div className="h-full flex items-end gap-1 px-6 pb-6 pt-10">
        {CHART_BAR_HEIGHTS.map((h, i) => (
          <Skeleton
            key={i}
            className="flex-1"
            style={{ height: `${h}%` }}
          />
        ))}
      </div>
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div
      className="bg-background border-[0.75px] border-border rounded-2xl overflow-hidden shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]"
    >
      <div className="px-4 py-3 border-b border-border flex gap-6">
        {[80, 40, 60, 60, 40, 50, 50].map((w, i) => (
          <Skeleton key={i} className="h-3" style={{ width: w }} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="px-4 py-3.5 border-b border-border last:border-0 flex gap-6">
          {[100, 40, 55, 55, 35, 45, 45].map((w, j) => (
            <Skeleton key={j} className="h-4" style={{ width: w }} />
          ))}
        </div>
      ))}
    </div>
  );
}
