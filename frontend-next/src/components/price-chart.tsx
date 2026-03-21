"use client";

import { useEffect, useRef, useCallback } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  ColorType,
  type CandlestickData,
  type Time,
  CandlestickSeries,
  HistogramSeries,
} from "lightweight-charts";
import { cn } from "@/lib/utils";

interface PriceChartProps {
  data: CandlestickData<Time>[];
  volumeData?: Array<{ time: Time; value: number; color: string }>;
  height?: number;
  className?: string;
}

export function PriceChart({
  data,
  volumeData,
  height = 320,
  className,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const isDark = useCallback(() => {
    if (typeof document === "undefined") return true;
    return document.documentElement.classList.contains("dark");
  }, []);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    const dark = isDark();
    const bgColor = dark ? "rgba(10, 15, 26, 0.95)" : "#ffffff";
    const textColor = dark ? "#64748b" : "#85857e";
    const gridColor = dark ? "rgba(30, 41, 59, 0.3)" : "#f0f0ec";
    const borderColor = dark ? "rgba(51, 65, 85, 0.4)" : "#e8e8e3";

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: bgColor },
        textColor,
        fontFamily: "var(--font-sans), sans-serif",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: gridColor },
        horzLines: { color: gridColor },
      },
      crosshair: {
        vertLine: { color: dark ? "rgba(0, 204, 177, 0.3)" : borderColor, width: 1, style: 3 },
        horzLine: { color: dark ? "rgba(0, 204, 177, 0.3)" : borderColor, width: 1, style: 3 },
      },
      rightPriceScale: {
        borderColor: dark ? "rgba(51, 65, 85, 0.3)" : borderColor,
      },
      timeScale: {
        borderColor: dark ? "rgba(51, 65, 85, 0.3)" : borderColor,
        timeVisible: false,
      },
    });
    chartRef.current = chart;

    const candleSeries: ISeriesApi<"Candlestick"> = chart.addSeries(
      CandlestickSeries,
      {
        upColor: "#34d399",
        downColor: "#fb7185",
        borderDownColor: "#fb7185",
        borderUpColor: "#34d399",
        wickDownColor: "#fb718580",
        wickUpColor: "#34d39980",
      }
    );
    candleSeries.setData(data);

    if (volumeData && volumeData.length > 0) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      volumeSeries.setData(
        volumeData.map((v) => ({
          ...v,
          color: v.color.includes("38,166,154")
            ? "rgba(16, 185, 129, 0.3)"
            : "rgba(244, 63, 94, 0.3)",
        }))
      );
    }

    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver(([entry]) => {
      chart.applyOptions({ width: entry.contentRect.width });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [data, volumeData, height, isDark]);

  if (data.length === 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center rounded-2xl bg-[#0a0f1a]/95 backdrop-blur-xl border border-slate-700/30 text-slate-500 text-sm",
          className
        )}
        style={{ height }}
      >
        No price data available
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={cn(
        "rounded-2xl overflow-hidden border border-slate-700/30",
        "shadow-[0_0_20px_rgba(0,0,0,0.3)]",
        className
      )}
      style={{ height }}
    />
  );
}
