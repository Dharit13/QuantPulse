"use client";

import { PulseLoader, PulseInline } from "@/components/pulse-loader";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { AICard } from "@/components/ai-card";
import { TradeCard } from "@/components/trade-card";
import { Badge } from "@/components/badge";
import { useScannerScan } from "@/context/scan-context";
import { CacheAge } from "@/components/cache-age";
import { apiPost } from "@/lib/api";
import { formatDollar } from "@/lib/utils";
import type { AIResult, BadgeVariant } from "@/lib/types";

interface ScanResult {
  regime?: string;
  signals: Array<{
    signal?: {
      ticker: string;
      direction: string;
      strategy: string;
      signal_score: number;
      conviction?: number;
      entry_price: number;
      stop_loss: number;
      target: number;
      edge_reason: string;
    };
    ticker?: string;
    direction?: string;
    strategy?: string;
    signal_score?: number;
    conviction?: number;
    entry_price?: number;
    stop_loss?: number;
    target?: number;
    edge_reason?: string;
  }>;
}

function normalizeSignal(raw: ScanResult["signals"][number]) {
  const s = raw.signal ?? raw;
  return {
    ticker: s.ticker ?? "",
    direction: (s.direction ?? "long").toUpperCase(),
    strategy: (s.strategy ?? "").replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase()),
    score: s.signal_score ?? 0,
    conviction: s.conviction ?? 0,
    entry: s.entry_price ?? 0,
    stop: s.stop_loss ?? 0,
    target: s.target ?? 0,
    edge: s.edge_reason ?? "",
  };
}

interface SignalExplainAI {
  result: {
    explanations: Array<{ ticker: string; simple: string }>;
  } | null;
}

export default function ScannerPage() {
  const scan = useScannerScan<ScanResult>();
  const [aiResult, setAiResult] = useState<AIResult["result"] | null>(null);
  const [simpleMap, setSimpleMap] = useState<Record<string, string>>({});
  const [aiLoading, setAiLoading] = useState(false);

  const signals = scan.result?.signals ?? [];
  const normalized = signals
    .map(normalizeSignal)
    .sort((a, b) => b.conviction - a.conviction || b.score - a.score)
    .slice(0, 10);

  useEffect(() => {
    if (scan.status !== "done" || !scan.result) return;
    setAiLoading(true);

    const sigs = signals.slice(0, 10).map((raw) => {
      const s = raw.signal ?? raw;
      return {
        ticker: s.ticker,
        direction: s.direction,
        strategy: s.strategy,
        signal_score: s.signal_score,
        edge_reason: s.edge_reason,
      };
    });

    Promise.all([
      apiPost<AIResult>("/ai/summarize", {
        type: "scan",
        data: { regime: scan.result.regime ?? "unknown", signals: sigs },
      }),
      apiPost<SignalExplainAI>("/ai/summarize", {
        type: "signal_explain",
        data: { signals: sigs },
      }),
    ]).then(([summaryRes, explainRes]) => {
      setAiResult(summaryRes?.result ?? null);
      if (explainRes?.result?.explanations) {
        const map: Record<string, string> = {};
        for (const e of explainRes.result.explanations) {
          map[e.ticker] = e.simple;
        }
        setSimpleMap(map);
      }
      setAiLoading(false);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scan.status]);

  const pct =
    scan.total > 0 ? Math.round((scan.progress / scan.total) * 100) : 0;

  return (
    <>
      <PageHeader
        title="Signal Scanner"
        subtitle="Find stocks where something interesting is happening"
        description="Finds long-term investment opportunities (6-12 months) by looking for WHY a stock might grow — company insiders buying their own stock, strong earnings, or analyst upgrades. AI picks the 50 most promising stocks to investigate based on current news and market conditions. Different from Swing Picks, which finds short-term trades (3-10 days)."
        actions={
          <div className="flex items-center gap-2">
            {scan.status === "done" && scan.resultTimestamp && (
              <CacheAge timestamp={scan.resultTimestamp} />
            )}
            <button
              onClick={() =>
                scan.start("/scan/start-scan", {
                  max_signals: 10,
                  min_score: 55,
                })
              }
              disabled={scan.isLoading}
              className="flex items-center gap-2 px-5 py-2.5 bg-accent text-white rounded-xl text-sm font-semibold hover:bg-accent-light transition-colors shadow-sm disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {scan.isLoading && <PulseInline />}
              {scan.isLoading ? "Scanning..." : scan.result ? "Refresh Scan" : "Scan Now"}
            </button>
          </div>
        }
      />

      {/* Scanning progress */}
      {scan.status === "scanning" && (
        <div
          className="bg-card border border-border rounded-2xl px-8 py-10 text-center mb-6"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <PulseLoader
            size="lg"
            label={`Scanning stocks... ${pct}%`}
            progress={pct}
            sublabel={scan.step || "AI is selecting and analyzing the most promising stocks right now."}
          />
        </div>
      )}

      {/* Error */}
      {scan.status === "error" && (
        <div className="bg-qp-red-bg border border-qp-red/15 rounded-2xl px-8 py-6 text-center mb-6">
          <div className="text-[15px] font-semibold text-qp-red mb-1">
            Scan failed
          </div>
          <p className="text-[13px] text-text-muted">{scan.error}</p>
        </div>
      )}

      {/* Idle */}
      {scan.status === "idle" && (
        <div
          className="bg-card border border-border rounded-2xl px-8 py-12 text-center"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <div className="w-14 h-14 rounded-2xl bg-accent-bg mx-auto flex items-center justify-center mb-4">
            <svg className="w-7 h-7 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-text-primary mb-2">
            Ready to Scan
          </h3>
          <p className="text-text-secondary text-sm max-w-md mx-auto">
            Click <strong>Scan Now</strong> — AI will pick the 50 most
            interesting S&P 500 stocks based on today&apos;s news and market
            conditions, then check each one for insider buying, earnings
            surprises, and analyst upgrades. Results in about 1 minute.
          </p>
        </div>
      )}

      {/* Results */}
      {scan.status === "done" && normalized.length > 0 && (
        <>
          {/* AI Analysis */}
          {aiLoading && (
            <div className="flex items-center gap-2 text-text-muted text-sm mb-4">
              <PulseInline />
              AI analyzing signals...
            </div>
          )}

          {aiResult && (
            <AICard title="Scan Analysis" accentColor="#539616">
              {aiResult.scan_summary_simple && (
                <p className="text-text-primary">{aiResult.scan_summary_simple}</p>
              )}
              {aiResult.scan_summary && (
                <p className="text-[12px] text-text-muted font-mono mt-1">
                  {aiResult.scan_summary}
                </p>
              )}
              {aiResult.top_pick_simple && (
                <div className="mt-3 px-4 py-3 bg-qp-green-bg rounded-xl border border-qp-green/15">
                  <div className="text-[13px] text-text-primary">
                    <span className="font-semibold text-qp-green">Top Pick:</span>{" "}
                    {aiResult.top_pick_simple}
                  </div>
                  {aiResult.top_pick && (
                    <div className="text-[12px] text-text-muted font-mono mt-1">
                      {aiResult.top_pick}
                    </div>
                  )}
                </div>
              )}
            </AICard>
          )}

          {/* Signal count */}
          <h3 className="text-[18px] font-bold text-text-primary mb-4 mt-6">
            Top {normalized.length} Signals
          </h3>

          {/* Signal cards — ranked by conviction */}
          {normalized.map((s, i) => {
            const dirLabel = s.direction === "LONG" ? "Buy" : "Sell Short";
            const dirBadge: BadgeVariant = s.direction === "LONG" ? "green" : "red";
            const risk = Math.abs(s.entry - s.stop);
            const reward = Math.abs(s.target - s.entry);
            const rr = risk > 0 ? `${(reward / risk).toFixed(1)}:1` : "—";
            const gainPct = s.entry > 0 ? ((s.target - s.entry) / s.entry * 100).toFixed(0) : "?";
            const lossPct = s.entry > 0 ? ((s.entry - s.stop) / s.entry * 100).toFixed(0) : "?";
            const simple = simpleMap[s.ticker];

            return (
              <TradeCard
                key={`${s.ticker}-${i}`}
                ticker={s.ticker}
                rank={i + 1}
                price={s.entry}
                badges={[
                  { text: dirLabel, variant: dirBadge },
                  { text: s.strategy, variant: "blue" },
                ]}
                stats={[
                  { label: "Entry", value: formatDollar(s.entry) },
                  { label: "Stop", value: formatDollar(s.stop), color: "#d44040" },
                  { label: "Target", value: formatDollar(s.target), color: "#2d9d3a" },
                  { label: "Reward/Risk", value: rr },
                ]}
                entrySignal={simple ? {
                  ticker: s.ticker,
                  label: i === 0 ? "Top Pick" : `#${i + 1} Pick`,
                  detail: `Could gain +${gainPct}% · Could lose -${lossPct}%`,
                  simple,
                  variant: i === 0 ? "green" : i < 3 ? "blue" : "gray",
                  isAI: true,
                } : undefined}
                meta={!simple ? s.edge : undefined}
              />
            );
          })}
        </>
      )}

      {/* Done but no signals */}
      {scan.status === "done" && normalized.length === 0 && (
        <div
          className="bg-card border border-border rounded-2xl px-8 py-10 text-center"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <p className="text-text-secondary text-sm">
            No strong signals found. The market may not have clear opportunities
            right now.
          </p>
        </div>
      )}
    </>
  );
}
