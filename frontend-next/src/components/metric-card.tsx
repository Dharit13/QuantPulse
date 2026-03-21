"use client";

import { type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { motion } from "framer-motion";
import { AnimatedNumber } from "./animated-number";
import { GlowingEffect } from "./ui/glowing-effect";

interface MetricCardProps {
  label: string;
  value: string;
  delta?: string;
  deltaColor?: "green" | "red" | "neutral";
  valueColor?: string;
  className?: string;
  animate?: boolean;
  tooltip?: ReactNode;
  bare?: boolean;
}

const numericRegex = /^[\d,.$+\-]+$/;

function extractNumber(str: string): number | null {
  const cleaned = str.replace(/[,$%+]/g, "");
  const n = parseFloat(cleaned);
  return isNaN(n) ? null : n;
}

export function MetricCard({
  label,
  value,
  delta,
  deltaColor = "neutral",
  valueColor,
  className,
  animate = true,
  tooltip,
  bare = false,
}: MetricCardProps) {
  const deltaStyles = {
    green: "text-emerald-400",
    red: "text-rose-400",
    neutral: "text-foreground/60",
  };

  const numericValue = extractNumber(value);
  const isNumeric = numericValue !== null && numericRegex.test(value.trim());
  const prefix = value.startsWith("$") ? "$" : value.startsWith("+") ? "+" : "";
  const suffix = value.endsWith("%") ? "%" : "";

  const formatAnimatedValue = (n: number) => {
    if (prefix === "$") {
      if (Math.abs(n) >= 1000) return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
      if (Math.abs(n) >= 100) return `$${n.toFixed(0)}`;
      return `$${n.toFixed(2)}`;
    }
    if (suffix === "%") {
      return `${prefix}${n.toFixed(1)}%`;
    }
    if (value.includes(".")) {
      const decimals = value.split(".")[1]?.replace(/[^0-9]/g, "").length ?? 1;
      return `${prefix}${n.toFixed(decimals)}${suffix}`;
    }
    return `${prefix}${Math.round(n).toLocaleString()}${suffix}`;
  };

  const content = (
    <>
      <div className="text-[12px] text-foreground/60 font-medium mb-1 flex items-center">
        {label}
        {tooltip}
      </div>
      <div
        className="font-bold text-2xl tracking-tight"
        style={{ color: valueColor || undefined }}
      >
        {animate && isNumeric && numericValue !== null ? (
          <AnimatedNumber
            value={numericValue}
            format={formatAnimatedValue}
            className={!valueColor ? "text-foreground" : undefined}
          />
        ) : (
          <>
            {!valueColor && <span className="text-foreground">{value}</span>}
            {valueColor && value}
          </>
        )}
      </div>
      {delta && (
        <div
          className={cn("text-[12px] font-medium mt-1", deltaStyles[deltaColor])}
        >
          {delta}
        </div>
      )}
    </>
  );

  if (bare) {
    return (
      <motion.div
        className={cn("px-0 py-0", className)}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.25, 0.46, 0.45, 0.94] }}
      >
        {content}
      </motion.div>
    );
  }

  return (
    <motion.div
      className={cn(
        "relative rounded-[1.25rem] border-[0.75px] border-border p-1.5 md:rounded-[1.5rem] md:p-2 h-full",
        className
      )}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.25, 0.46, 0.45, 0.94] }}
    >
      <GlowingEffect
        spread={40}
        glow
        disabled={false}
        proximity={64}
        inactiveZone={0.01}
        borderWidth={2}
      />
      <div className="relative rounded-xl border-[0.75px] border-border bg-background px-5 py-4 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)] h-full">
        {content}
      </div>
    </motion.div>
  );
}
