"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { useSSEScan } from "@/hooks/use-sse-scan";
import type { AnalysisData } from "@/lib/types";

interface AnalysisState {
  ticker: string;
  capital: number;
  data: AnalysisData | null;
  loading: boolean;
  progress: number;
  total: number;
  step: string;
  error: string | null;
  setTicker: (v: string) => void;
  setCapital: (v: number | ((prev: number) => number)) => void;
  analyze: () => void;
}

const AnalysisContext = createContext<AnalysisState | null>(null);

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [ticker, setTicker] = useState("AAPL");
  const [capital, setCapital] = useState(10000);

  const scan = useSSEScan<AnalysisData>(
    "stock-analysis",
    "/analyze/stream",
    "/analyze/status",
  );

  const tickerRef = useRef(ticker);
  tickerRef.current = ticker;
  const capitalRef = useRef(capital);
  capitalRef.current = capital;

  const analyze = useCallback(() => {
    const t = tickerRef.current.trim();
    if (!t) return;
    scan.start("/analyze/start", { ticker: t, capital: capitalRef.current });
  }, [scan]);

  return (
    <AnalysisContext.Provider
      value={{
        ticker,
        capital,
        data: scan.result,
        loading: scan.isLoading,
        progress: scan.progress,
        total: scan.total,
        step: scan.step,
        error: scan.error,
        setTicker,
        setCapital,
        analyze,
      }}
    >
      {children}
    </AnalysisContext.Provider>
  );
}

export function useAnalysis() {
  const ctx = useContext(AnalysisContext);
  if (!ctx) throw new Error("useAnalysis must be inside AnalysisProvider");
  return ctx;
}
