"use client";

interface MarketActionBannerProps {
  tone: "bullish" | "cautious" | "bearish" | "crisis";
  headline: string;
  detail: string;
}

const TONE_CONFIG: Record<
  MarketActionBannerProps["tone"],
  { bg: string; border: string; icon: string; iconColor: string; accentBg: string }
> = {
  bullish: {
    bg: "bg-qp-green-bg",
    border: "border-qp-green/20",
    icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6",
    iconColor: "#2d9d3a",
    accentBg: "bg-qp-green/10",
  },
  cautious: {
    bg: "bg-qp-amber-bg",
    border: "border-qp-amber/20",
    icon: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z",
    iconColor: "#c6a339",
    accentBg: "bg-qp-amber/10",
  },
  bearish: {
    bg: "bg-qp-red-bg",
    border: "border-qp-red/10",
    icon: "M13 17h8m0 0V9m0 8l-8-8-4 4-6-6",
    iconColor: "#d44040",
    accentBg: "bg-qp-red/10",
  },
  crisis: {
    bg: "bg-qp-red-bg",
    border: "border-qp-red/20",
    icon: "M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
    iconColor: "#d44040",
    accentBg: "bg-qp-red/15",
  },
};

export function MarketActionBanner({ tone, headline, detail }: MarketActionBannerProps) {
  const cfg = TONE_CONFIG[tone] ?? TONE_CONFIG.cautious;

  return (
    <div
      className={`${cfg.bg} border ${cfg.border} rounded-2xl px-6 py-5 mb-6 flex items-center gap-5`}
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div
        className={`shrink-0 w-12 h-12 rounded-xl ${cfg.accentBg} flex items-center justify-center`}
      >
        <svg
          className="w-6 h-6"
          fill="none"
          stroke={cfg.iconColor}
          strokeWidth={2.5}
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d={cfg.icon} />
        </svg>
      </div>
      <div className="min-w-0">
        <div className="text-[17px] font-bold text-text-primary leading-snug">
          {headline}
        </div>
        <p className="text-[13px] text-text-body mt-0.5 leading-relaxed">
          {detail}
        </p>
      </div>
    </div>
  );
}
