"use client";

import { SlideUp } from "@/components/motion-primitives";
import { PulseLoader, PulseInline } from "@/components/pulse-loader";
import { PageHeader } from "@/components/page-header";
import { TradeCard } from "@/components/trade-card";
import { CacheAge } from "@/components/cache-age";
import { useSSEScan } from "@/hooks/use-sse-scan";
import { formatDollar } from "@/lib/utils";
import { GradientCard, GradientButton } from "@/components/gradient-card";
import { GlowingEffect } from "@/components/ui/glowing-effect";
import type { BadgeVariant } from "@/lib/types";

interface ScanResult {
  regime?: string;
  total_signals?: number;
  timestamp?: string;
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
      max_hold_days?: number;
      kelly_size_pct?: number;
    };
    final_recommendation?: string;
    shadow_evidence?: {
      win_rate?: number;
      phantom_count?: number;
      avg_pnl_pct?: number;
      has_enough_data?: boolean;
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
    max_hold_days?: number;
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
    maxHoldDays: s.max_hold_days ?? 0,
    recommendation: raw.final_recommendation ?? "",
    winRate: raw.shadow_evidence?.win_rate,
    shadowCount: raw.shadow_evidence?.phantom_count ?? 0,
    shadowHasData: raw.shadow_evidence?.has_enough_data ?? false,
  };
}

export default function ScannerPage() {
  const scan = useSSEScan<ScanResult>(
    "scanner",
    "/scan/stream",
    "/scan/status",
  );

  const signals = scan.result?.signals ?? [];
  const normalized = signals
    .map(normalizeSignal)
    .sort((a, b) => b.conviction - a.conviction || b.score - a.score)
    .slice(0, 10);

  const aiResult = scan.aiSummary;
  const simpleMap: Record<string, string> = {};
  if (scan.signalExplanations?.explanations) {
    for (const e of scan.signalExplanations.explanations) {
      simpleMap[e.ticker] = e.simple;
    }
  }

  const pct =
    scan.total > 0 ? Math.round((scan.progress / scan.total) * 100) : 0;

  return (
    <>
      <PageHeader
        title="Signal Scanner"
        subtitle="Find stocks where something interesting is happening"
        description="Finds medium to long-term investment opportunities (1-6 months) by looking for WHY a stock might grow — company insiders buying their own stock, strong earnings, or analyst upgrades. AI picks the 50 most promising stocks to investigate based on current news and market conditions. Different from Swing Picks, which finds short-term trades (3-10 days)."
        actions={
          <div className="flex items-center gap-2">
            {scan.status === "done" && scan.resultTimestamp && (
              <CacheAge timestamp={scan.resultTimestamp} />
            )}
            <GradientButton
              onClick={() =>
                scan.start("/scan/start-scan", {
                  max_signals: 10,
                  min_score: 55,
                })
              }
              disabled={scan.isLoading}
            >
              {scan.isLoading && <PulseInline />}
              {scan.isLoading ? "Scanning..." : scan.result ? "Refresh Scan" : "Scan Now"}
            </GradientButton>
          </div>
        }
      />

      {/* Scanning progress */}
      {scan.status === "scanning" && (
        <GradientCard className="mb-6" innerClassName="px-8 py-10 text-center">
          <PulseLoader
            size="lg"
            label={`Scanning stocks... ${pct}%`}
            progress={pct}
            sublabel={scan.step || "AI is selecting and analyzing the most promising stocks right now."}
          />
        </GradientCard>
      )}

      {/* Error */}
      {scan.status === "error" && (
        <GradientCard className="mb-6" innerClassName="px-8 py-6 text-center">
          <div className="text-[15px] font-semibold text-rose-400 mb-1">
            Scan failed
          </div>
          <p className="text-[13px] text-foreground/60">{scan.error}</p>
        </GradientCard>
      )}

      {/* Idle */}
      {scan.status === "idle" && (
        <SlideUp>
        <GradientCard innerClassName="px-8 py-12 text-center">
          <div className="w-14 h-14 rounded-2xl bg-blue-500/5 mx-auto flex items-center justify-center mb-4">
            <svg className="w-7 h-7 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-foreground mb-2">
            Ready to Scan
          </h3>
          <p className="text-foreground/80 text-sm max-w-md mx-auto">
            Click <strong>Scan Now</strong> — AI will pick the 50 most
            interesting S&P 500 stocks based on today&apos;s news and market
            conditions, then check each one for insider buying, earnings
            surprises, and analyst upgrades. Results in about 1 minute.
          </p>
        </GradientCard>
        </SlideUp>
      )}

      {/* Results */}
      {scan.status === "done" && normalized.length > 0 && (
        <div className="relative rounded-[1.25rem] border-[0.75px] border-border p-2 md:rounded-[1.5rem] md:p-3">
          <GlowingEffect
            spread={40}
            glow
            disabled={false}
            proximity={64}
            inactiveZone={0.01}
            borderWidth={3}
          />
          <div className="relative rounded-xl border-[0.75px] border-border bg-background px-6 py-5 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
            <h3 className="text-[18px] font-bold text-foreground mb-4">
              Top {normalized.length} Signals
            </h3>

            {/* AI Analysis */}
            {aiResult && (
              <div className="mb-6 pb-5 border-b border-border">
                {aiResult.scan_summary_simple && (
                  <p className="text-[14px] font-medium text-foreground">{aiResult.scan_summary_simple}</p>
                )}
                {aiResult.scan_summary && (
                  <p className="text-[12px] text-foreground/60 mt-1">
                    {aiResult.scan_summary}
                  </p>
                )}
                {aiResult.top_pick_simple && (
                  <div className="mt-3 px-4 py-3 bg-emerald-500/5 rounded-xl border border-emerald-500/15">
                    <div className="text-[13px] text-foreground">
                      <span className="font-semibold text-emerald-400">Top Pick:</span>{" "}
                      {aiResult.top_pick_simple}
                    </div>
                    {aiResult.top_pick && (
                      <div className="text-[12px] text-foreground/60 mt-1">
                        {aiResult.top_pick}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Signal cards */}
            {normalized.map((s, i) => {
              const dirLabel = s.direction === "LONG" ? "Buy" : "Sell Short";
              const dirBadge: BadgeVariant = s.direction === "LONG" ? "green" : "red";
              const risk = Math.abs(s.entry - s.stop);
              const reward = Math.abs(s.target - s.entry);
              const rr = risk > 0 ? `${(reward / risk).toFixed(1)}:1` : "—";
              const gainPct = s.entry > 0 ? ((s.target - s.entry) / s.entry * 100).toFixed(0) : "?";
              const lossPct = s.entry > 0 ? ((s.entry - s.stop) / s.entry * 100).toFixed(0) : "?";
              const simple = simpleMap[s.ticker];

              const scoreVariant: BadgeVariant =
                s.score >= 70 ? "green" : s.score >= 50 ? "amber" : "red";

              const recVariant: BadgeVariant =
                s.recommendation === "trade"
                  ? "green"
                  : s.recommendation === "conditional_trade"
                    ? "amber"
                    : s.recommendation === "do_not_trade"
                      ? "red"
                      : "gray";
              const recLabel =
                s.recommendation === "trade"
                  ? "Trade"
                  : s.recommendation === "conditional_trade"
                    ? "Conditional"
                    : s.recommendation === "do_not_trade"
                      ? "Do Not Trade"
                      : "";

              const badges: Array<{ text: string; variant: BadgeVariant }> = [
                { text: dirLabel, variant: dirBadge },
                { text: s.strategy, variant: "blue" },
                { text: `Score ${s.score.toFixed(0)}`, variant: scoreVariant },
              ];
              if (recLabel) {
                badges.push({ text: recLabel, variant: recVariant });
              }

              const stats = [
                { label: "Entry", value: formatDollar(s.entry) },
                { label: "Stop", value: formatDollar(s.stop), color: "#fb7185" },
                { label: "Target", value: formatDollar(s.target), color: "#34d399" },
                { label: "R/R", value: rr },
              ];
              if (s.maxHoldDays > 0) {
                stats.push({ label: "Hold", value: `${s.maxHoldDays}d` });
              }
              if (s.shadowHasData && s.winRate !== undefined) {
                stats.push({
                  label: "Win Rate",
                  value: `${(s.winRate * 100).toFixed(0)}%`,
                  color: s.winRate >= 0.5 ? "#34d399" : "#fb7185",
                });
              }

              return (
                <TradeCard
                  key={`${s.ticker}-${i}`}
                  index={i}
                  ticker={s.ticker}
                  rank={i + 1}
                  price={s.entry}
                  badges={badges}
                  stats={stats}
                  entrySignal={simple ? {
                    ticker: s.ticker,
                    label: i === 0 ? "Top Pick" : `#${i + 1} Pick`,
                    detail: `Could gain +${gainPct}% · Could lose -${lossPct}%${s.shadowHasData && s.winRate !== undefined ? ` · ${(s.winRate * 100).toFixed(0)}% win rate from ${s.shadowCount} similar trades` : ""}`,
                    simple,
                    variant: i === 0 ? "green" : i < 3 ? "blue" : "gray",
                    isAI: true,
                  } : undefined}
                  meta={!simple ? s.edge : undefined}
                />
              );
            })}

            {/* Scan stats */}
            {scan.result && (
              <div className="mt-4 pt-4 border-t border-border">
                <p className="text-[12px] text-foreground/60">
                  {scan.result.total_signals
                    ? `Found ${scan.result.total_signals} total signals, showing top ${normalized.length}.`
                    : `Showing top ${normalized.length} signals.`}
                  {" "}These are medium to long-term (1-6 month) investment opportunities.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Done but no signals */}
      {scan.status === "done" && normalized.length === 0 && (
        <GradientCard innerClassName="px-8 py-10 text-center">
          <p className="text-foreground/80 text-sm">
            No strong signals found. The market may not have clear opportunities
            right now.
          </p>
        </GradientCard>
      )}
    </>
  );
}
