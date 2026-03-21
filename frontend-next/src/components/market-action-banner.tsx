"use client";

import { motion } from "framer-motion";
import { GlowingEffect } from "./ui/glowing-effect";

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
    bg: "bg-emerald-500/5",
    border: "border-emerald-500/20",
    icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6",
    iconColor: "#34d399",
    accentBg: "bg-emerald-500/10",
  },
  cautious: {
    bg: "bg-amber-500/5",
    border: "border-amber-500/20",
    icon: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z",
    iconColor: "#fbbf24",
    accentBg: "bg-amber-500/10",
  },
  bearish: {
    bg: "bg-rose-500/5",
    border: "border-rose-500/20",
    icon: "M13 17h8m0 0V9m0 8l-8-8-4 4-6-6",
    iconColor: "#fb7185",
    accentBg: "bg-rose-500/10",
  },
  crisis: {
    bg: "bg-rose-500/8",
    border: "border-rose-500/20",
    icon: "M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
    iconColor: "#fb7185",
    accentBg: "bg-rose-500/15",
  },
};

export function MarketActionBanner({ tone, headline, detail }: MarketActionBannerProps) {
  const cfg = TONE_CONFIG[tone] ?? TONE_CONFIG.cautious;

  return (
    <motion.div
      className="relative rounded-[1.25rem] border-[0.75px] border-border p-2 mb-6 md:rounded-[1.5rem] md:p-3"
      initial={{ opacity: 0, y: -12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.5, ease: [0.25, 0.46, 0.45, 0.94] }}
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
        className={`relative rounded-xl border-[0.75px] ${cfg.border} ${cfg.bg} bg-background px-6 py-5 flex items-center gap-5 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]`}
      >
        <motion.div
          className={`shrink-0 w-12 h-12 rounded-xl ${cfg.accentBg} flex items-center justify-center`}
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ duration: 0.4, delay: 0.15, ease: [0.34, 1.56, 0.64, 1] }}
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
        </motion.div>
        <div className="min-w-0">
          <div className="text-[17px] font-bold text-foreground leading-snug">
            {headline}
          </div>
          <p className="text-[13px] text-foreground/80 mt-0.5 leading-relaxed">
            {detail}
          </p>
        </div>
      </div>
    </motion.div>
  );
}
