"use client";

import { type ReactNode } from "react";
import {
  motion,
  type Variants,
  type HTMLMotionProps,
} from "framer-motion";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

// ---------------------------------------------------------------------------
// FadeIn — simple opacity entrance
// ---------------------------------------------------------------------------
interface FadeInProps extends Omit<HTMLMotionProps<"div">, "children"> {
  children: ReactNode;
  delay?: number;
  duration?: number;
}

export function FadeIn({
  children,
  delay = 0,
  duration = 0.4,
  ...props
}: FadeInProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration, delay, ease: "easeOut" }}
      {...props}
    >
      {children}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// SlideUp — fade in with upward translation
// ---------------------------------------------------------------------------
interface SlideUpProps extends Omit<HTMLMotionProps<"div">, "children"> {
  children: ReactNode;
  delay?: number;
  duration?: number;
  distance?: number;
}

export function SlideUp({
  children,
  delay = 0,
  duration = 0.45,
  distance = 16,
  ...props
}: SlideUpProps) {
  const noMotion = prefersReducedMotion();
  return (
    <motion.div
      initial={{ opacity: 0, y: noMotion ? 0 : distance }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration, delay, ease: [0.25, 0.46, 0.45, 0.94] }}
      {...props}
    >
      {children}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// SlideIn — fade in from left/right
// ---------------------------------------------------------------------------
interface SlideInProps extends Omit<HTMLMotionProps<"div">, "children"> {
  children: ReactNode;
  delay?: number;
  duration?: number;
  direction?: "left" | "right";
  distance?: number;
}

export function SlideIn({
  children,
  delay = 0,
  duration = 0.4,
  direction = "left",
  distance = 20,
  ...props
}: SlideInProps) {
  const x = direction === "left" ? -distance : distance;
  return (
    <motion.div
      initial={{ opacity: 0, x }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration, delay, ease: "easeOut" }}
      {...props}
    >
      {children}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// StaggerGroup — container that staggers child animations
// ---------------------------------------------------------------------------
const staggerContainerVariants: Variants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.06,
      delayChildren: 0.1,
    },
  },
};

const staggerItemVariants: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: [0.25, 0.46, 0.45, 0.94] },
  },
};

interface StaggerGroupProps extends Omit<HTMLMotionProps<"div">, "children"> {
  children: ReactNode;
  staggerDelay?: number;
  initialDelay?: number;
}

export function StaggerGroup({
  children,
  staggerDelay = 0.06,
  initialDelay = 0.1,
  ...props
}: StaggerGroupProps) {
  const variants: Variants = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: staggerDelay,
        delayChildren: initialDelay,
      },
    },
  };

  return (
    <motion.div
      variants={variants}
      initial="hidden"
      animate="visible"
      {...props}
    >
      {children}
    </motion.div>
  );
}

interface StaggerItemProps extends Omit<HTMLMotionProps<"div">, "children"> {
  children: ReactNode;
}

export function StaggerItem({ children, ...props }: StaggerItemProps) {
  return (
    <motion.div variants={staggerItemVariants} {...props}>
      {children}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// ScaleIn — pop-in with slight scale
// ---------------------------------------------------------------------------
export function ScaleIn({
  children,
  delay = 0,
  ...props
}: {
  children: ReactNode;
  delay?: number;
} & Omit<HTMLMotionProps<"div">, "children">) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.35, delay, ease: [0.34, 1.56, 0.64, 1] }}
      {...props}
    >
      {children}
    </motion.div>
  );
}

// Re-export stagger variants for direct use with motion.div
export { staggerContainerVariants, staggerItemVariants };
