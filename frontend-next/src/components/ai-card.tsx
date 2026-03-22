"use client";

import { cn } from "@/lib/utils";
import { motion } from "framer-motion";
import { GlowingEffect } from "./ui/glowing-effect";

interface AICardProps {
  title: string;
  children: React.ReactNode;
  accentColor?: string;
  className?: string;
}

export function AICard({
  title,
  children,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  accentColor = "#00ccb1",
  className,
}: AICardProps) {
  return (
    <motion.div
      className={cn(
        "relative rounded-[1.25rem] border-[0.75px] border-border p-2 mb-3 md:rounded-[1.5rem] md:p-3",
        className
      )}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
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
        className="relative rounded-xl border-[0.75px] border-border bg-background px-6 py-5 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]"
      >
        <h3 className="text-[15px] font-semibold text-foreground mb-2">
          {title}
        </h3>
        <div className="text-[14px] leading-[1.7] text-foreground/80">{children}</div>
      </div>
    </motion.div>
  );
}
