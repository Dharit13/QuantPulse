"use client";

import { useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Info } from "lucide-react";

interface MetricTooltipProps {
  content: string;
  children?: ReactNode;
}

export function MetricTooltip({ content, children }: MetricTooltipProps) {
  const [open, setOpen] = useState(false);

  return (
    <span
      className="relative inline-flex items-center"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {children ?? (
        <Info className="h-3.5 w-3.5 text-foreground/80 hover:text-foreground cursor-help transition-colors ml-1" />
      )}
      <AnimatePresence>
        {open && (
          <motion.div
            className="absolute z-40 bottom-full left-1/2 mb-2 w-56 px-3 py-2.5 rounded-xl bg-background border border-border text-[12px] text-foreground/80 leading-relaxed pointer-events-none shadow-2xl"
            style={{ transform: "translateX(-50%)" }}
            initial={{ opacity: 0, y: 4, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.96 }}
            transition={{ duration: 0.15 }}
          >
            {content}
            <div
              className="absolute top-full left-1/2 -translate-x-1/2 w-2.5 h-2.5 rotate-45 bg-background border-r border-b border-border"
              style={{ marginTop: -5 }}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </span>
  );
}

export const METRIC_TOOLTIPS: Record<string, string> = {
  regime:
    "The current market state detected by our regime model — bull, bear, choppy, or crisis. Determines which strategies get more allocation.",
  vix:
    "VIX measures expected market volatility (fear). Below 15 = calm, 20-30 = nervous, above 30 = panic. Higher VIX means more defensive positioning.",
  breadth:
    "Percentage of S&P 500 stocks trading above their 200-day average. Above 60% = healthy broad rally. Below 40% = most stocks are falling.",
  adx:
    "Average Directional Index — measures trend strength regardless of direction. Above 25 = clear trend. Below 20 = choppy, no direction.",
};
