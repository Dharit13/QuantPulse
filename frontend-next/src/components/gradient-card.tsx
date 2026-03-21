"use client";

import { cn } from "@/lib/utils";
import { motion } from "framer-motion";
import { GlowingEffect } from "./ui/glowing-effect";
import type { ReactNode } from "react";

interface GradientCardProps {
  children: ReactNode;
  className?: string;
  innerClassName?: string;
  animate?: boolean;
  delay?: number;
}

export function GradientCard({
  children,
  className,
  innerClassName,
  animate = true,
  delay = 0,
}: GradientCardProps) {
  return (
    <motion.div
      className={cn(
        "relative rounded-[1.25rem] border-[0.75px] border-border p-2 md:p-3 md:rounded-[1.5rem]",
        className
      )}
      initial={animate ? { opacity: 0, y: 16 } : undefined}
      animate={animate ? { opacity: 1, y: 0 } : undefined}
      transition={animate ? { duration: 0.5, delay, ease: [0.25, 0.46, 0.45, 0.94] } : undefined}
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
        className={cn(
          "relative flex flex-col justify-between rounded-xl border-[0.75px] border-border bg-background p-6 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]",
          "h-full",
          innerClassName
        )}
      >
        {children}
      </div>
    </motion.div>
  );
}

export function GradientButton({
  children,
  onClick,
  disabled,
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "relative rounded-[1rem] border-[0.75px] border-border p-1.5 cursor-pointer active:scale-[0.97] transition-transform disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100",
        className
      )}
    >
      <GlowingEffect
        spread={40}
        glow
        disabled={false}
        proximity={64}
        inactiveZone={0.01}
        borderWidth={2}
      />
      <div className="relative rounded-[0.5rem] border-[0.75px] border-border bg-background px-6 py-2.5 text-sm font-semibold text-foreground flex items-center gap-2">
        {children}
      </div>
    </button>
  );
}
