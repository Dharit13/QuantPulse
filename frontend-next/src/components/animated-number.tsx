"use client";

import { useEffect, useRef } from "react";
import {
  useMotionValue,
  useSpring,
  useTransform,
  motion,
  type SpringOptions,
} from "framer-motion";

interface AnimatedNumberProps {
  value: number;
  format?: (n: number) => string;
  springOptions?: SpringOptions;
  className?: string;
}

const DEFAULT_SPRING: SpringOptions = {
  stiffness: 120,
  damping: 20,
  mass: 0.8,
};

export function AnimatedNumber({
  value,
  format,
  springOptions,
  className,
}: AnimatedNumberProps) {
  const motionValue = useMotionValue(0);
  const spring = useSpring(motionValue, { ...DEFAULT_SPRING, ...springOptions });
  const display = useTransform(spring, (v) =>
    format ? format(v) : v.toFixed(0)
  );
  const ref = useRef<HTMLSpanElement>(null);
  const hasRendered = useRef(false);

  useEffect(() => {
    if (!hasRendered.current) {
      motionValue.set(value);
      hasRendered.current = true;
    } else {
      motionValue.set(value);
    }
  }, [value, motionValue]);

  return (
    <motion.span ref={ref} className={className}>
      {display}
    </motion.span>
  );
}

export function AnimatedPercent({
  value,
  decimals = 1,
  suffix = "%",
  className,
}: {
  value: number;
  decimals?: number;
  suffix?: string;
  className?: string;
}) {
  return (
    <AnimatedNumber
      value={value}
      format={(n) => `${n.toFixed(decimals)}${suffix}`}
      className={className}
    />
  );
}

export function AnimatedDollar({
  value,
  className,
}: {
  value: number;
  className?: string;
}) {
  return (
    <AnimatedNumber
      value={value}
      format={(n) => {
        if (n >= 1000) return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
        if (n >= 100) return `$${n.toFixed(0)}`;
        return `$${n.toFixed(2)}`;
      }}
      className={className}
    />
  );
}
