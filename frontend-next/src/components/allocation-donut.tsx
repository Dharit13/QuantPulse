"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { motion } from "framer-motion";
import { AnimatedPercent } from "./animated-number";

interface AllocationSlice {
  key: string;
  label: string;
  value: number;
  color: string;
}

interface AllocationDonutProps {
  slices: AllocationSlice[];
  investedPct: number;
  className?: string;
}

export function AllocationDonut({
  slices,
  investedPct,
  className,
}: AllocationDonutProps) {
  const data = slices.filter((s) => s.value >= 0.01);

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5, ease: [0.25, 0.46, 0.45, 0.94] }}
    >
      <div className="relative w-full" style={{ height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <defs>
              {data.map((entry) => (
                <linearGradient key={`grad-${entry.key}`} id={`grad-${entry.key}`} x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor={entry.color} stopOpacity={1} />
                  <stop offset="100%" stopColor={entry.color} stopOpacity={0.6} />
                </linearGradient>
              ))}
              <filter id="donut-glow">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            <Pie
              data={data}
              dataKey="value"
              nameKey="label"
              cx="50%"
              cy="50%"
              innerRadius="58%"
              outerRadius="88%"
              paddingAngle={3}
              strokeWidth={0}
              animationBegin={200}
              animationDuration={800}
              animationEasing="ease-out"
              filter="url(#donut-glow)"
            >
              {data.map((entry) => (
                <Cell key={entry.key} fill={`url(#grad-${entry.key})`} />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0];
                return (
                  <div className="bg-background border border-border rounded-xl px-4 py-2.5 text-[12px] shadow-2xl">
                    <div className="font-semibold text-foreground">
                      {d.name}
                    </div>
                    <div className="text-foreground/80 mt-0.5">
                      {Math.round((d.value as number) * 100)}%
                    </div>
                  </div>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-3xl font-black leading-none bg-gradient-to-r from-[#00ccb1] to-[#1ca0fb] bg-clip-text text-transparent">
            <AnimatedPercent value={investedPct * 100} decimals={0} />
          </span>
          <span className="text-[11px] text-foreground/80 mt-1 font-medium">in market</span>
        </div>
      </div>
      <div className="flex flex-wrap justify-center gap-x-5 gap-y-1.5 mt-3">
        {data.map((s) => (
          <div key={s.key} className="flex items-center gap-2">
            <span
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{
                background: s.color,
                boxShadow: `0 0 6px ${s.color}60`,
              }}
            />
            <span className="text-[11px] text-foreground/80 font-medium">{s.label}</span>
          </div>
        ))}
      </div>
    </motion.div>
  );
}
