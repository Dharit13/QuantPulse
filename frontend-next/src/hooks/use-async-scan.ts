"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { apiPost, apiGet } from "@/lib/api";

interface ScanState<T> {
  status: "idle" | "scanning" | "done" | "error";
  progress: number;
  total: number;
  step?: string;
  universeSize?: number;
  result: T | null;
  error: string | null;
  isLoading: boolean;
}

interface StatusResponse<T> {
  status: string;
  progress?: number;
  total?: number;
  step?: string;
  universe_size?: number;
  result?: T;
  error?: string;
}

export function useAsyncScan<T>(
  statusUrl: string,
  pollIntervalMs = 3000
) {
  const [state, setState] = useState<ScanState<T>>({
    status: "idle",
    progress: 0,
    total: 0,
    result: null,
    error: null,
    isLoading: false,
  });

  const mountedRef = useRef(true);
  const pollingActiveRef = useRef(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initialCheckDone = useRef(false);

  const applyStatus = useCallback((data: StatusResponse<T>) => {
    if (data.status === "done" && data.result) {
      pollingActiveRef.current = false;
      setState({
        status: "done",
        progress: data.total ?? 0,
        total: data.total ?? 0,
        result: data.result as T,
        error: null,
        isLoading: false,
      });
      return "done";
    } else if (data.status === "error") {
      pollingActiveRef.current = false;
      setState((prev) => ({
        ...prev,
        status: "error",
        error: data.error ?? "Scan failed",
        isLoading: false,
      }));
      return "error";
    } else if (data.status === "scanning") {
      setState((prev) => ({
        ...prev,
        status: "scanning",
        progress: data.progress ?? prev.progress,
        total: data.total ?? prev.total,
        step: data.step,
        universeSize: data.universe_size ?? prev.universeSize,
        isLoading: true,
      }));
      return "scanning";
    }
    return data.status;
  }, []);

  const poll = useCallback(async () => {
    if (!mountedRef.current || !pollingActiveRef.current) return;

    const data = await apiGet<StatusResponse<T>>(statusUrl);

    if (!mountedRef.current || !pollingActiveRef.current) return;
    if (!data) {
      timeoutRef.current = setTimeout(poll, pollIntervalMs);
      return;
    }

    const result = applyStatus(data);
    if (result === "scanning") {
      timeoutRef.current = setTimeout(poll, pollIntervalMs);
    }
  }, [statusUrl, pollIntervalMs, applyStatus]);

  // On mount: check backend status to recover from navigation
  useEffect(() => {
    mountedRef.current = true;

    if (!initialCheckDone.current) {
      initialCheckDone.current = true;

      apiGet<StatusResponse<T>>(statusUrl).then((data) => {
        if (!mountedRef.current || !data) return;

        if (data.status === "done" && data.result) {
          applyStatus(data);
        } else if (data.status === "scanning") {
          applyStatus(data);
          pollingActiveRef.current = true;
          timeoutRef.current = setTimeout(poll, pollIntervalMs);
        }
        // If "idle" or "error" — leave as idle, user can start fresh
      });
    }

    return () => {
      mountedRef.current = false;
      pollingActiveRef.current = false;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [statusUrl, poll, pollIntervalMs, applyStatus]);

  // Resume polling when tab becomes visible
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible" && pollingActiveRef.current) {
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        poll();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [poll]);

  const start = useCallback(
    async (
      startUrl: string,
      params?: Record<string, string | number>
    ) => {
      setState({
        status: "scanning",
        progress: 0,
        total: 0,
        result: null,
        error: null,
        isLoading: true,
      });

      const resp = await apiPost<{ status: string }>(
        startUrl,
        undefined,
        params
      );

      if (
        !resp ||
        !["started", "already_scanning"].includes(resp.status)
      ) {
        setState((prev) => ({
          ...prev,
          status: "error",
          error: "Failed to start scan",
          isLoading: false,
        }));
        return;
      }

      pollingActiveRef.current = true;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(poll, 500);
    },
    [poll]
  );

  const reset = useCallback(() => {
    pollingActiveRef.current = false;
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setState({
      status: "idle",
      progress: 0,
      total: 0,
      result: null,
      error: null,
      isLoading: false,
    });
  }, []);

  return { ...state, start, reset };
}
