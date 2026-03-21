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

interface SwingResult {
  quick_trades: SwingTrade[];
  swing_trades: SwingTrade[];
  scan_stats: { tickers_scanned: number };
}

interface SwingTrade {
  ticker: string;
  name?: string;
  sector?: string;
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
  rsi?: number;
  volume_ratio?: number;
  atr_pct?: number;
  ret_1d?: number;
  ret_5d?: number;
  analyst_target?: number;
  earnings_warning?: string;
}

export default function SwingPicksPage() {
  const scan = useSSEScan<SwingResult>(
    "swing",
    "/swing/stream",
    "/swing/status",
  );

  const allPicks = [
    ...(scan.result?.quick_trades ?? []),
    ...(scan.result?.swing_trades ?? []),
  ]
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);

  const stats = scan.result?.scan_stats;
  const aiResult = scan.aiSummary;

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
            <GradientButton
              onClick={() =>
                scan.start("/swing/start-scan", {
                  min_return_pct: 30,
                  max_hold_days: 10,
                })
              }
              disabled={scan.isLoading}
            >
              {scan.isLoading && <PulseInline />}
              {scan.isLoading ? "Scanning..." : scan.result ? "Rescan" : "Find Swings"}
            </GradientButton>
          </div>
        }
      />

      {/* Scanning progress */}
      {scan.status === "scanning" && (
        <GradientCard className="mb-6" innerClassName="px-8 py-10 text-center">
          <PulseLoader
            size="lg"
            label={`Scanning for swing trades... ${pct}%`}
            progress={pct}
            sublabel={scan.step || "Scanning 100+ stocks for aggressive setups targeting 30%+ returns."}
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

      {/* Idle — risk warning */}
      {scan.status === "idle" && (
        <SlideUp>
          <GradientCard innerClassName="px-8 py-10 border-l-4 border-l-rose-500">
            <h3 className="text-lg font-semibold text-foreground mb-2">
              Short-Term Swing Trades
            </h3>
            <p className="text-[14px] text-foreground/80 leading-relaxed">
              Click <strong>Find Swings</strong> to scan 100+ stocks for
              aggressive short-term setups targeting{" "}
              <strong>30%+ returns in 3-10 days</strong>.
            </p>
            <p className="text-[13px] text-rose-400 mt-3 font-medium">
              These are volatile, high-risk trades. Size small — 1-2% of your
              capital max per trade.
            </p>
          </GradientCard>
        </SlideUp>
      )}

      {/* Results */}
      {scan.status === "done" && allPicks.length > 0 && (
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
              Top {allPicks.length} Setups
            </h3>

            {/* AI Analysis */}
            {aiResult && (
              <div className="mb-6 pb-5 border-b border-border">
                {aiResult.swing_summary_simple && (
                  <p className="text-[14px] font-medium text-foreground">
                    {aiResult.swing_summary_simple}
                  </p>
                )}
                {aiResult.swing_summary && (
                  <p className="text-[12px] text-foreground/60 mt-1">
                    {aiResult.swing_summary}
                  </p>
                )}
                {(aiResult.top_pick_advice_simple || aiResult.top_pick_advice) && (
                  <div className="mt-3 px-4 py-3 bg-rose-500/5 rounded-xl border border-rose-500/15">
                    {aiResult.top_pick_advice_simple && (
                      <div className="text-[13px] text-foreground">
                        <span className="font-semibold text-rose-400">
                          Top Pick:
                        </span>{" "}
                        {aiResult.top_pick_advice_simple}
                      </div>
                    )}
                    {aiResult.top_pick_advice && (
                      <div className="text-[12px] text-foreground/60 mt-1">
                        {aiResult.top_pick_advice}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Trade cards */}
            {allPicks.map((t, i) => {
              const dir = t.direction === "long" ? "LONG" : "SHORT";
              const dirBadge: BadgeVariant = dir === "LONG" ? "green" : "red";
              const riskBadge: BadgeVariant =
                t.risk_level === "EXTREME" || t.risk_level === "VERY HIGH"
                  ? "red"
                  : "amber";
              const scoreVariant: BadgeVariant =
                t.score >= 70 ? "green" : t.score >= 50 ? "amber" : "red";

              const badges: Array<{ text: string; variant: BadgeVariant }> = [
                { text: dir, variant: dirBadge },
                { text: t.risk_level, variant: riskBadge },
                { text: `Score ${t.score.toFixed(0)}`, variant: scoreVariant },
              ];
              if (t.sector && t.sector !== "Unknown") {
                badges.push({ text: t.sector, variant: "blue" });
              }
              if (t.earnings_warning) {
                badges.push({ text: "Earnings Soon", variant: "red" });
              }

              const rsiColor =
                t.rsi !== undefined
                  ? t.rsi < 35
                    ? "#34d399"
                    : t.rsi > 70
                      ? "#fb7185"
                      : undefined
                  : undefined;

              const tradeStats = [
                { label: "Entry", value: formatDollar(t.entry) },
                { label: "Target", value: formatDollar(t.target), color: "#34d399" },
                { label: "Stop", value: formatDollar(t.stop), color: "#fb7185" },
                { label: "R/R", value: `${t.risk_reward.toFixed(1)}:1` },
                { label: "Hold", value: `${t.hold_days}d` },
              ];

              if (t.rsi !== undefined) {
                tradeStats.push({ label: "RSI", value: t.rsi.toFixed(0), color: rsiColor });
              }
              if (t.volume_ratio !== undefined) {
                tradeStats.push({ label: "Volume", value: `${t.volume_ratio.toFixed(1)}x` });
              }
              if (t.atr_pct !== undefined) {
                tradeStats.push({ label: "ATR%", value: `${t.atr_pct.toFixed(1)}%` });
              }
              if (t.ret_1d !== undefined) {
                tradeStats.push({
                  label: "1D",
                  value: `${t.ret_1d >= 0 ? "+" : ""}${t.ret_1d.toFixed(1)}%`,
                  color: t.ret_1d >= 0 ? "#34d399" : "#fb7185",
                });
              }
              if (t.ret_5d !== undefined) {
                tradeStats.push({
                  label: "5D",
                  value: `${t.ret_5d >= 0 ? "+" : ""}${t.ret_5d.toFixed(1)}%`,
                  color: t.ret_5d >= 0 ? "#34d399" : "#fb7185",
                });
              }

              return (
                <TradeCard
                  key={`${t.ticker}-${i}`}
                  index={i}
                  ticker={t.ticker}
                  name={t.name}
                  rank={i + 1}
                  price={t.price}
                  badges={badges}
                  rightContent={
                    <span className="text-lg font-bold text-emerald-400">
                      +{t.return_pct.toFixed(0)}%
                    </span>
                  }
                  stats={tradeStats}
                  entrySignal={t.analysis ? {
                    ticker: t.ticker,
                    label: t.catalyst ?? "Setup",
                    detail: `Could gain +${t.return_pct.toFixed(0)}% · Risk: ${t.risk_level.toLowerCase()} · Hold ${t.hold_days} trading days${t.exit_window ? ` · ${t.exit_window}` : ""}${t.earnings_warning ? ` · ⚠ ${t.earnings_warning}` : ""}`,
                    simple: t.analysis,
                    variant: i === 0 ? "green" : i < 3 ? "blue" : "gray",
                    isAI: false,
                  } : undefined}
                />
              );
            })}

            {/* Scan stats */}
            {stats && (
              <div className="mt-4 pt-4 border-t border-border">
                <p className="text-[12px] text-foreground/60">
                  Scanned {stats.tickers_scanned} tickers. These are high-risk,
                  short-term trades. Size small (1-2% of capital max).
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Done but nothing found */}
      {scan.status === "done" && allPicks.length === 0 && (
        <GradientCard innerClassName="px-8 py-10 text-center">
          <p className="text-foreground/80 text-sm">
            No stocks found with 30%+ potential right now. Try again later.
          </p>
        </GradientCard>
      )}
    </>
  );
}
