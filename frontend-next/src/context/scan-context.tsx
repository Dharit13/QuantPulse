"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
  useMemo,
  type ReactNode,
} from "react";
import { apiPost, apiGet } from "@/lib/api";

interface ScanState<T> {
  status: "idle" | "scanning" | "done" | "error";
  progress: number;
  total: number;
  step?: string;
  universeSize?: number;
  result: T | null;
  resultTimestamp: string | null;
  error: string | null;
  isLoading: boolean;
}

interface ScanActions<T> extends ScanState<T> {
  start: (
    startUrl: string,
    params?: Record<string, string | number>
  ) => Promise<void>;
  reset: () => void;
}

const INITIAL: ScanState<never> = {
  status: "idle",
  progress: 0,
  total: 0,
  result: null,
  resultTimestamp: null,
  error: null,
  isLoading: false,
};

// ---------------------------------------------------------------------------
// Module-level stores — live outside React, survive remounts, Strict Mode
// double-fires, Fast Refresh, and any reconciliation quirk.
// ---------------------------------------------------------------------------
interface ModuleStore {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  state: ScanState<any>;
  pollingActive: boolean;
  timeout: ReturnType<typeof setTimeout> | null;
}

const stores: Record<string, ModuleStore> = {};

function getStore(key: string): ModuleStore {
  if (!stores[key]) {
    stores[key] = {
      state: { ...INITIAL },
      pollingActive: false,
      timeout: null,
    };
  }
  return stores[key];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ScannerContext = createContext<ScanActions<any> | null>(null);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const SwingContext = createContext<ScanActions<any> | null>(null);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const PortfolioContext = createContext<ScanActions<any> | null>(null);

// ---------------------------------------------------------------------------
// Core hook — reads/writes a module-level store so state persists across any
// React lifecycle event while still triggering re-renders via useState.
// ---------------------------------------------------------------------------
function usePersistentScan<T>(
  key: string,
  statusUrl: string,
  pollIntervalMs: number
): ScanActions<T> {
  const store = getStore(key);
  const mountedRef = useRef(true);

  const [state, rawSetState] = useState<ScanState<T>>(
    () => store.state as ScanState<T>
  );

  const setState = useCallback(
    (next: ScanState<T> | ((prev: ScanState<T>) => ScanState<T>)) => {
      rawSetState((prev) => {
        const value = typeof next === "function" ? next(prev) : next;
        store.state = value;
        return value;
      });
    },
    [store]
  );

  const stopPolling = useCallback(() => {
    store.pollingActive = false;
    if (store.timeout) {
      clearTimeout(store.timeout);
      store.timeout = null;
    }
  }, [store]);

  const poll = useCallback(async () => {
    if (!mountedRef.current || !store.pollingActive) return;

    try {
      const data = await apiGet<{
        status: string;
        progress?: number;
        total?: number;
        step?: string;
        universe_size?: number;
        result?: T;
        result_timestamp?: string;
        error?: string;
      }>(statusUrl);

      if (!mountedRef.current || !store.pollingActive) return;

      if (!data) {
        store.timeout = setTimeout(poll, pollIntervalMs);
        return;
      }

      if (data.status === "done" && data.result) {
        stopPolling();
        setState({
          status: "done",
          progress: data.total ?? 0,
          total: data.total ?? 0,
          result: data.result as T,
          resultTimestamp: data.result_timestamp ?? null,
          error: null,
          isLoading: false,
        });
      } else if (data.status === "error") {
        stopPolling();
        setState((prev) => ({
          ...prev,
          status: "error",
          error: data.error ?? "Scan failed",
          isLoading: false,
        }));
      } else if (data.status === "scanning") {
        setState((prev) => ({
          ...prev,
          status: "scanning",
          progress: data.progress ?? prev.progress,
          total: data.total ?? prev.total,
          step: data.step ?? prev.step,
          universeSize: data.universe_size ?? prev.universeSize,
          isLoading: true,
        }));
        store.timeout = setTimeout(poll, pollIntervalMs);
      } else {
        store.timeout = setTimeout(poll, pollIntervalMs);
      }
    } catch {
      if (mountedRef.current && store.pollingActive) {
        store.timeout = setTimeout(poll, pollIntervalMs * 2);
      }
    }
  }, [statusUrl, pollIntervalMs, stopPolling, setState, store]);

  // ---- Mount: hydrate from module store, or recover from backend ----------
  useEffect(() => {
    mountedRef.current = true;

    if (store.state.status !== "idle") {
      rawSetState(store.state as ScanState<T>);

      if (store.pollingActive) {
        if (store.timeout) clearTimeout(store.timeout);
        store.timeout = setTimeout(poll, 500);
      }
    } else {
      apiGet<{
        status: string;
        progress?: number;
        total?: number;
        universe_size?: number;
        result?: T;
        result_timestamp?: string;
        error?: string;
      }>(statusUrl).then((data) => {
        if (!mountedRef.current || !data) return;

        if (data.status === "done" && data.result) {
          setState({
            status: "done",
            progress: data.total ?? 0,
            total: data.total ?? 0,
            result: data.result as T,
            resultTimestamp: data.result_timestamp ?? null,
            error: null,
            isLoading: false,
          });
        } else if (data.status === "scanning") {
          setState((prev) => ({
            ...prev,
            status: "scanning",
            progress: data.progress ?? 0,
            total: data.total ?? 0,
            universeSize: data.universe_size,
            isLoading: true,
          }));
          store.pollingActive = true;
          store.timeout = setTimeout(poll, pollIntervalMs);
        }
      });
    }

    return () => {
      mountedRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Resume polling when tab becomes visible again ----------------------
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible" && store.pollingActive) {
        if (store.timeout) clearTimeout(store.timeout);
        poll();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [poll, store]);

  // ---- Actions ------------------------------------------------------------
  const start = useCallback(
    async (startUrl: string, params?: Record<string, string | number>) => {
      setState({
        status: "scanning",
        progress: 0,
        total: 0,
        result: null,
        resultTimestamp: null,
        error: null,
        isLoading: true,
      });

      const resp = await apiPost<{ status: string }>(
        startUrl,
        undefined,
        params
      );

      if (!resp || !["started", "already_scanning"].includes(resp.status)) {
        setState((prev) => ({
          ...prev,
          status: "error",
          error: "Failed to start scan",
          isLoading: false,
        }));
        return;
      }

      store.pollingActive = true;
      if (store.timeout) clearTimeout(store.timeout);
      store.timeout = setTimeout(poll, 500);
    },
    [poll, setState, store]
  );

  const reset = useCallback(() => {
    stopPolling();
    setState({ ...INITIAL } as ScanState<T>);
  }, [stopPolling, setState]);

  return useMemo(
    () => ({ ...state, start, reset }),
    [state, start, reset]
  );
}

// ---------------------------------------------------------------------------
// Provider + consumer hooks
// ---------------------------------------------------------------------------
export function ScanProvider({ children }: { children: ReactNode }) {
  const scanner = usePersistentScan("scanner", "/scan/status", 1500);
  const swing = usePersistentScan("swing", "/swing/status", 5000);
  const portfolio = usePersistentScan("portfolio", "/portfolio/quick-allocate/status", 2000);

  return (
    <ScannerContext.Provider value={scanner}>
      <SwingContext.Provider value={swing}>
        <PortfolioContext.Provider value={portfolio}>
          {children}
        </PortfolioContext.Provider>
      </SwingContext.Provider>
    </ScannerContext.Provider>
  );
}

export function useScannerScan<T>() {
  const ctx = useContext(ScannerContext);
  if (!ctx) throw new Error("useScannerScan must be inside ScanProvider");
  return ctx as ScanActions<T>;
}

export function useSwingScan<T>() {
  const ctx = useContext(SwingContext);
  if (!ctx) throw new Error("useSwingScan must be inside ScanProvider");
  return ctx as ScanActions<T>;
}

export function usePortfolioScan<T>() {
  const ctx = useContext(PortfolioContext);
  if (!ctx) throw new Error("usePortfolioScan must be inside ScanProvider");
  return ctx as ScanActions<T>;
}
