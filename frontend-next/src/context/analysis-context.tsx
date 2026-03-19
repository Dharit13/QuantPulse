"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { apiGet } from "@/lib/api";
import type { AnalysisData } from "@/lib/types";

interface AnalysisState {
  ticker: string;
  capital: number;
  data: AnalysisData | null;
  loading: boolean;
  error: string | null;
  setTicker: (v: string) => void;
  setCapital: (v: number | ((prev: number) => number)) => void;
  analyze: () => Promise<void>;
}

const AnalysisContext = createContext<AnalysisState | null>(null);

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [ticker, setTicker] = useState("AAPL");
  const [capital, setCapital] = useState(10000);
  const [data, setData] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tickerRef = useRef(ticker);
  tickerRef.current = ticker;
  const capitalRef = useRef(capital);
  capitalRef.current = capital;

  const analyze = useCallback(async () => {
    const t = tickerRef.current.trim();
    if (!t) return;
    setLoading(true);
    setError(null);
    setData(null);

    const result = await apiGet<AnalysisData>(
      `/analyze/${encodeURIComponent(t)}`,
      { capital: capitalRef.current }
    );

    if (!result) {
      setError(`Could not analyze "${t}". Check the backend is running.`);
    } else {
      setData(result);
    }
    setLoading(false);
  }, []);

  return (
    <AnalysisContext.Provider
      value={{
        ticker,
        capital,
        data,
        loading,
        error,
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
