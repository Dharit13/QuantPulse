import { cn } from "@/lib/utils";

interface AICardProps {
  title: string;
  children: React.ReactNode;
  accentColor?: string;
  className?: string;
}

export function AICard({
  title,
  children,
  accentColor = "#539616",
  className,
}: AICardProps) {
  return (
    <div
      className={cn(
        "bg-card border border-border rounded-2xl px-6 py-5 mb-3 transition-all duration-200 hover:shadow-[var(--shadow-card-hover)]",
        className
      )}
      style={{
        borderLeftWidth: 4,
        borderLeftColor: accentColor,
        boxShadow: "var(--shadow-card)",
      }}
    >
      <h3 className="text-[15px] font-semibold text-text-primary mb-2">
        {title}
      </h3>
      <div className="text-[14px] leading-[1.7] text-text-body">{children}</div>
    </div>
  );
}
