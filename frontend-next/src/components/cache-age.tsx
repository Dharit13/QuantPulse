"use client";

import { useState, useEffect } from "react";

interface CacheAgeProps {
  timestamp: string | null;
  className?: string;
}

function formatAge(isoTimestamp: string): string | null {
  const then = new Date(isoTimestamp + (isoTimestamp.endsWith("Z") ? "" : "Z"));
  if (isNaN(then.getTime())) return null;
  const diffMs = Date.now() - then.getTime();
  const diffMin = Math.floor(diffMs / 60_000);

  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `Updated ${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `Updated ${diffHr}h ago`;
  return `Updated ${Math.floor(diffHr / 24)}d ago`;
}

export function CacheAge({ timestamp, className }: CacheAgeProps) {
  const [label, setLabel] = useState(() =>
    timestamp ? formatAge(timestamp) : null
  );

  useEffect(() => {
    if (!timestamp) {
      setLabel(null);
      return;
    }
    setLabel(formatAge(timestamp));
    const id = setInterval(() => setLabel(formatAge(timestamp)), 30_000);
    return () => clearInterval(id);
  }, [timestamp]);

  if (!label) return null;

  return (
    <span className={className ?? "text-[12px] text-text-muted"}>
      {label}
    </span>
  );
}
