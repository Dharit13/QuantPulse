"use client";

import { PulseLoader, PulseInline } from "@/components/pulse-loader";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { AICard } from "@/components/ai-card";
import { TradeCard } from "@/components/trade-card";
import { useSwingScan } from "@/context/scan-context";
import { CacheAge } from "@/components/cache-age";
import { apiGet, apiPost } from "@/lib/api";
import { formatDollar } from "@/lib/utils";
import type { AIResult, RegimeData, BadgeVariant } from "@/lib/types";

interface SwingResult {
  quick_trades: SwingTrade[];
  swing_trades: SwingTrade[];
  scan_stats: { tickers_scanned: number };
}

interface SwingTrade {
  ticker: string;
  price: number;
  direction: string;
  entry: number;
  target: number;
  stop: number;
  return_pct: number;
  risk_reward: number;
  hold_days: number;
  exit_window?: string;
  score: number;
  risk_level: string;
  catalyst?: string;
  analysis?: string;
}

export default function SwingPicksPage() {
  const scan = useSwingScan<SwingResult>();
  const [aiResult, setAiResult] = useState<AIResult["result"] | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

  const allPicks = [
    ...(scan.result?.quick_trades ?? []),
    ...(scan.result?.swing_trades ?? []),
  ]
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);

  const stats = scan.result?.scan_stats;

  useEffect(() => {
    if (scan.status !== "done" || allPicks.length === 0) return;
    setAiLoading(true);

    (async () => {
      const regime = await apiGet<RegimeData>("/regime/current");
      const regimeStr = regime?.regime ?? "unknown";

      const res = await apiPost<AIResult>("/ai/summarize", {
        type: "swing",
        data: { regime: regimeStr, picks: allPicks },
      });
      setAiResult(res?.result ?? null);
      setAiLoading(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scan.status]);

  const pct =
    scan.total > 0 ? Math.round((scan.progress / scan.total) * 100) : 0;

  return (
    <>
      <PageHeader
        title="Swing Picks"
        subtitle="Short-term trades you hold for a few days"
        description="These are fast, aggressive bets — you buy a stock and sell it within 3-10 days aiming for 30%+ returns. Think of it like day trading but over a few days. High risk, high reward. Only use money you can afford to lose, and never put more than 1-2% of your total capital in a single trade."
        actions={
          <div className="flex items-center gap-2">
            {scan.status === "done" && scan.resultTimestamp && (
              <CacheAge timestamp={scan.resultTimestamp} />
            )}
            <button
              onClick={() =>
                scan.start("/swing/start-scan", {
                  min_return_pct: 30,
                  max_hold_days: 10,
                })
              }
              disabled={scan.isLoading}
              className="flex items-center gap-2 px-5 py-2.5 bg-accent text-white rounded-xl text-sm font-semibold hover:bg-accent-light transition-colors shadow-sm disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {scan.isLoading && <PulseInline />}
              {scan.isLoading ? "Scanning..." : scan.result ? "Rescan" : "Find Swings"}
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
            label={`Scanning for swing trades... ${pct}%`}
            progress={pct}
            sublabel="Scanning 100+ stocks for aggressive setups targeting 30%+ returns."
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

      {/* Idle — risk warning */}
      {scan.status === "idle" && (
        <div
          className="bg-card border border-border rounded-2xl px-8 py-10"
          style={{
            boxShadow: "var(--shadow-card)",
            borderLeft: "4px solid #d44040",
          }}
        >
          <h3 className="text-lg font-semibold text-text-primary mb-2">
            Short-Term Swing Trades
          </h3>
          <p className="text-[14px] text-text-body leading-relaxed">
            Click <strong>Find Swings</strong> to scan 100+ stocks for
            aggressive short-term setups targeting{" "}
            <strong>30%+ returns in 3-10 days</strong>.
          </p>
          <p className="text-[13px] text-qp-red mt-3 font-medium">
            These are volatile, high-risk trades. Size small — 1-2% of your
            capital max per trade.
          </p>
        </div>
      )}

      {/* Results */}
      {scan.status === "done" && allPicks.length > 0 && (
        <>
          {/* AI Analysis */}
          {aiLoading && (
            <div className="flex items-center gap-2 text-text-muted text-sm mb-4">
              <PulseInline />
              AI analyzing setups...
            </div>
          )}

          {aiResult && (
            <AICard title="Swing Analysis" accentColor="#d44040">
              {aiResult.swing_summary_simple && (
                <p className="text-text-primary">
                  {aiResult.swing_summary_simple}
                </p>
              )}
              {aiResult.swing_summary && (
                <p className="text-[12px] text-text-muted font-mono mt-1">
                  {aiResult.swing_summary}
                </p>
              )}
              {(aiResult.top_pick_advice_simple || aiResult.top_pick_advice) && (
                <div
                  className="mt-3 px-4 py-3 bg-qp-red-bg rounded-xl border border-qp-red/15"
                >
                  {aiResult.top_pick_advice_simple && (
                    <div className="text-[13px] text-text-primary">
                      <span className="font-semibold text-qp-red">
                        Top Pick:
                      </span>{" "}
                      {aiResult.top_pick_advice_simple}
                    </div>
                  )}
                  {aiResult.top_pick_advice && (
                    <div className="text-[12px] text-text-muted font-mono mt-1">
                      {aiResult.top_pick_advice}
                    </div>
                  )}
                </div>
              )}
            </AICard>
          )}

          {/* Picks */}
          <h3 className="text-[18px] font-bold text-text-primary mb-4 mt-6">
            Top {allPicks.length} Setups
          </h3>

          {allPicks.map((t, i) => {
            const dir = t.direction === "long" ? "LONG" : "SHORT";
            const dirBadge: BadgeVariant = dir === "LONG" ? "green" : "red";
            const riskBadge: BadgeVariant =
              t.risk_level === "EXTREME" || t.risk_level === "VERY HIGH"
                ? "red"
                : "amber";
            const scoreVariant: BadgeVariant =
              t.score >= 70 ? "green" : t.score >= 50 ? "amber" : "red";

            return (
              <TradeCard
                key={`${t.ticker}-${i}`}
                ticker={t.ticker}
                rank={i + 1}
                price={t.price}
                badges={[
                  { text: dir, variant: dirBadge },
                  { text: t.risk_level, variant: riskBadge },
                  { text: `Score ${t.score.toFixed(0)}`, variant: scoreVariant },
                ]}
                rightContent={
                  <span className="font-mono text-lg font-bold text-qp-green">
                    +{t.return_pct.toFixed(0)}%
                  </span>
                }
                stats={[
                  { label: "Entry", value: formatDollar(t.entry) },
                  {
                    label: "Target",
                    value: formatDollar(t.target),
                    color: "#2d9d3a",
                  },
                  {
                    label: "Stop",
                    value: formatDollar(t.stop),
                    color: "#d44040",
                  },
                  { label: "Reward/Risk", value: `${t.risk_reward.toFixed(1)}:1` },
                  { label: "Hold", value: `${t.hold_days} trading days` },
                ]}
                entrySignal={t.analysis ? {
                  ticker: t.ticker,
                  label: t.catalyst ?? "Setup",
                  detail: `Could gain +${t.return_pct.toFixed(0)}% · Risk: ${t.risk_level.toLowerCase()} · Hold ${t.hold_days} trading days${t.exit_window ? ` · ${t.exit_window}` : ""}`,
                  simple: t.analysis,
                  variant: i === 0 ? "green" : i < 3 ? "blue" : "gray",
                  isAI: false,
                } : undefined}
              />
            );
          })}

          {/* Scan stats */}
          {stats && (
            <p className="text-[12px] text-text-muted mt-4">
              Scanned {stats.tickers_scanned} tickers. These are high-risk,
              short-term trades. Size small (1-2% of capital max).
            </p>
          )}

          
        </>
      )}

      {/* Done but nothing found */}
      {scan.status === "done" && allPicks.length === 0 && (
        <div
          className="bg-card border border-border rounded-2xl px-8 py-10 text-center"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <p className="text-text-secondary text-sm">
            No stocks found with 30%+ potential right now. Try again later.
          </p>
        </div>
      )}
    </>
  );
}
