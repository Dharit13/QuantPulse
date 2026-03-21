"use client";

import { type ReactNode } from "react";
import { GradientCard } from "./gradient-card";
import { AnimatedNumber } from "./animated-number";

interface HeroMetric {
  label: string;
  value: string;
  numericValue?: number;
  valueColor: string;
  delta: string;
  deltaColor: "green" | "red" | "neutral";
  tooltip?: ReactNode;
}

const DELTA_STYLES = {
  green: "text-emerald-400",
  red: "text-rose-400",
  neutral: "text-foreground/80",
};

function extractNumber(str: string): number | null {
  const cleaned = str.replace(/[,$%+]/g, "");
  const n = parseFloat(cleaned);
  return isNaN(n) ? null : n;
}

function HeroMetricCard({ metric, index }: { metric: HeroMetric; index: number }) {
  const numVal = metric.numericValue ?? extractNumber(metric.value);
  const isNumeric = numVal !== null;

  const prefix = metric.value.startsWith("$") ? "$" : metric.value.startsWith("+") ? "+" : "";
  const suffix = metric.value.endsWith("%") ? "%" : "";

  const formatValue = (n: number) => {
    if (prefix === "$") {
      if (Math.abs(n) >= 1000) return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
      if (Math.abs(n) >= 100) return `$${n.toFixed(0)}`;
      return `$${n.toFixed(2)}`;
    }
    if (suffix === "%") return `${prefix}${n.toFixed(1)}%`;
    if (metric.value.includes(".")) {
      const decimals = metric.value.split(".")[1]?.replace(/[^0-9]/g, "").length ?? 1;
      return `${prefix}${n.toFixed(decimals)}${suffix}`;
    }
    return `${prefix}${Math.round(n).toLocaleString()}${suffix}`;
  };

  return (
    <GradientCard delay={index * 0.08}>
      <div className="flex items-center gap-2 mb-3">
        <span
          className="w-2 h-2 rounded-full"
          style={{
            backgroundColor: metric.valueColor,
            boxShadow: `0 0 8px ${metric.valueColor}80`,
          }}
        />
        <span className="text-[11px] font-semibold text-foreground/80 uppercase tracking-[0.1em]">
          {metric.label}
        </span>
        {metric.tooltip}
      </div>

      <div className="mb-2">
        {isNumeric && numVal !== null ? (
          <AnimatedNumber
            value={numVal}
            format={formatValue}
            className="font-black text-4xl tracking-tight leading-none text-foreground"
          />
        ) : (
          <span
            className="font-black text-4xl tracking-tight leading-none"
            style={{ color: metric.valueColor }}
          >
            {metric.value}
          </span>
        )}
      </div>

      <p className={`text-[13px] font-medium leading-snug ${DELTA_STYLES[metric.deltaColor]}`}>
        {metric.delta}
      </p>
    </GradientCard>
  );
}

export function HeroMetrics({ metrics }: { metrics: HeroMetric[] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 mb-10">
      {metrics.map((m, i) => (
        <HeroMetricCard key={m.label} metric={m} index={i} />
      ))}
    </div>
  );
}
