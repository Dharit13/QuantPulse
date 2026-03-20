"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { apiPost, apiGet } from "@/lib/api";
import type { AIResult } from "@/lib/types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

interface SSEScanState<T> {
  status: "idle" | "scanning" | "done" | "error";
  progress: number;
  total: number;
  step: string;
  result: T | null;
  resultTimestamp: string | null;
  aiSummary: AIResult["result"] | null;
  signalExplanations: { explanations?: Array<{ ticker: string; simple: string }> } | null;
  error: string | null;
  isLoading: boolean;
}

export interface SSEScanActions<T> extends SSEScanState<T> {
  start: (
    startUrl: string,
    params?: Record<string, string | number>,
  ) => Promise<void>;
  reset: () => void;
}

const INITIAL: SSEScanState<never> = {
  status: "idle",
  progress: 0,
  total: 0,
  step: "",
  result: null,
  resultTimestamp: null,
  aiSummary: null,
  signalExplanations: null,
  error: null,
  isLoading: false,
};

// Module-level stores survive React remounts, Fast Refresh, Strict Mode
interface ModuleStore {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  state: SSEScanState<any>;
  eventSource: EventSource | null;
}

const stores: Record<string, ModuleStore> = {};

function getStore(key: string): ModuleStore {
  if (!stores[key]) {
    stores[key] = { state: { ...INITIAL }, eventSource: null };
  }
  return stores[key];
}

/**
 * SSE-based scan hook — replaces polling with a persistent EventSource
 * connection that streams real-time progress from the backend.
 *
 * @param key     Unique store key ("scanner" | "swing")
 * @param sseUrl  SSE stream path, e.g. "/scan/stream"
 * @param statusUrl  Polling-fallback path for initial hydration, e.g. "/scan/status"
 */
export function useSSEScan<T>(
  key: string,
  sseUrl: string,
  statusUrl: string,
): SSEScanActions<T> {
  const store = getStore(key);
  const mountedRef = useRef(true);

  const [state, rawSetState] = useState<SSEScanState<T>>(
    () => store.state as SSEScanState<T>,
  );

  const setState = useCallback(
    (next: SSEScanState<T> | ((prev: SSEScanState<T>) => SSEScanState<T>)) => {
      rawSetState((prev) => {
        const value = typeof next === "function" ? next(prev) : next;
        store.state = value;
        return value;
      });
    },
    [store],
  );

  const closeSSE = useCallback(() => {
    if (store.eventSource) {
      store.eventSource.close();
      store.eventSource = null;
    }
  }, [store]);

  const connectSSE = useCallback(() => {
    closeSSE();

    const es = new EventSource(`${API_BASE}${sseUrl}`);
    store.eventSource = es;

    es.onmessage = (event) => {
      if (!mountedRef.current) return;
      try {
        const data = JSON.parse(event.data);

        if (data.status === "done" && data.result) {
          closeSSE();
          setState({
            status: "done",
            progress: data.total ?? 100,
            total: data.total ?? 100,
            step: data.step ?? "",
            result: data.result as T,
            resultTimestamp: data.result_timestamp ?? null,
            aiSummary: data.ai_summary ?? null,
            signalExplanations: data.signal_explanations ?? null,
            error: null,
            isLoading: false,
          });
        } else if (data.status === "error") {
          closeSSE();
          setState((prev) => ({
            ...prev,
            status: "error",
            step: "",
            error: data.error ?? "Scan failed",
            isLoading: false,
          }));
        } else if (data.status === "idle") {
          closeSSE();
          if (data.result) {
            setState({
              status: "done",
              progress: 100,
              total: 100,
              step: "",
              result: data.result as T,
              resultTimestamp: data.result_timestamp ?? null,
              aiSummary: data.ai_summary ?? null,
              signalExplanations: data.signal_explanations ?? null,
              error: null,
              isLoading: false,
            });
          }
        } else if (data.status === "scanning") {
          setState((prev) => ({
            ...prev,
            status: "scanning",
            progress: data.progress ?? prev.progress,
            total: data.total ?? prev.total,
            step: data.step ?? prev.step,
            isLoading: true,
          }));
        }
      } catch {
        // JSON parse error — ignore malformed event
      }
    };

    es.onerror = () => {
      closeSSE();
      // Reconnect after a short delay if still scanning
      if (mountedRef.current && store.state.status === "scanning") {
        setTimeout(() => {
          if (mountedRef.current && store.state.status === "scanning") {
            connectSSE();
          }
        }, 2000);
      }
    };
  }, [sseUrl, closeSSE, setState, store]);

  // On mount: hydrate from module store, or recover from backend
  useEffect(() => {
    mountedRef.current = true;

    if (store.state.status !== "idle") {
      rawSetState(store.state as SSEScanState<T>);
      if (store.state.status === "scanning" && !store.eventSource) {
        connectSSE();
      }
    } else {
      apiGet<{
        status: string;
        progress?: number;
        total?: number;
        step?: string;
        result?: T;
        result_timestamp?: string;
        ai_summary?: AIResult["result"];
        signal_explanations?: SSEScanState<T>["signalExplanations"];
        error?: string;
      }>(statusUrl).then((data) => {
        if (!mountedRef.current || !data) return;

        if ((data.status === "done" || data.status === "idle") && data.result) {
          setState({
            status: "done",
            progress: data.total ?? 100,
            total: data.total ?? 100,
            step: "",
            result: data.result as T,
            resultTimestamp: data.result_timestamp ?? null,
            aiSummary: data.ai_summary ?? null,
            signalExplanations: data.signal_explanations ?? null,
            error: null,
            isLoading: false,
          });
        } else if (data.status === "scanning") {
          setState((prev) => ({
            ...prev,
            status: "scanning",
            progress: data.progress ?? 0,
            total: data.total ?? 0,
            step: data.step ?? "",
            isLoading: true,
          }));
          connectSSE();
        }
      });
    }

    return () => {
      mountedRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reconnect SSE when tab becomes visible
  useEffect(() => {
    const onVisible = () => {
      if (
        document.visibilityState === "visible" &&
        store.state.status === "scanning" &&
        !store.eventSource
      ) {
        connectSSE();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [connectSSE, store]);

  const start = useCallback(
    async (startUrl: string, params?: Record<string, string | number>) => {
      closeSSE();
      setState({
        status: "scanning",
        progress: 0,
        total: 0,
        step: "Starting scan...",
        result: null,
        resultTimestamp: null,
        aiSummary: null,
        signalExplanations: null,
        error: null,
        isLoading: true,
      });

      const resp = await apiPost<{ status: string }>(
        startUrl,
        undefined,
        params,
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

      // Small delay to let the backend initialize state before SSE connects
      setTimeout(connectSSE, 300);
    },
    [closeSSE, connectSSE, setState],
  );

  const reset = useCallback(() => {
    closeSSE();
    setState({ ...INITIAL } as SSEScanState<T>);
  }, [closeSSE, setState]);

  return useMemo(
    () => ({ ...state, start, reset }),
    [state, start, reset],
  );
}
