"use client";

import { useEffect, useState, useCallback } from "react";
import { ChevronDown } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { PulseLoader, PulseInline } from "@/components/pulse-loader";
import { AICard } from "@/components/ai-card";
import { TradeCard } from "@/components/trade-card";
import { Badge } from "@/components/badge";
import { MarketActionBanner } from "@/components/market-action-banner";
import { CacheAge } from "@/components/cache-age";
import { AnimatedNumber } from "@/components/animated-number";
import { HeroMetrics } from "@/components/hero-metrics";
import { GradientCard, GradientButton } from "@/components/gradient-card";
import { GlowingEffect } from "@/components/ui/glowing-effect";
import { AllocationDonut } from "@/components/allocation-donut";
import { SectorTable } from "@/components/sector-table";
import { MetricTooltip, METRIC_TOOLTIPS } from "@/components/metric-tooltip";
import { apiGet, apiPost } from "@/lib/api";
import { formatDollar } from "@/lib/utils";
import { fallbackEntrySignal, type EntrySignal } from "@/lib/entry-timing";
import { useSSEScan } from "@/hooks/use-sse-scan";
import type {
  RegimeData,
  AIResult,
  SectorRecommendations,
  BadgeVariant,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MarketActionAI {
  result: {
    tone: "bullish" | "cautious" | "bearish" | "crisis";
    headline: string;
    detail: string;
  } | null;
}

interface RegimeProbsAI {
  result: {
    action?: string;
    timing?: string;
    news_sentiment?: string;
  };
}

interface AllocationAI {
  result: {
    strategies: Array<{
      key: string;
      name: string;
      explanation: string;
    }>;
  } | null;
}

// ---------------------------------------------------------------------------
// Module-level cache
// ---------------------------------------------------------------------------

interface DashboardCache {
  regime: RegimeData | null;
  aiResult: AIResult["result"] | null;
  regimeAI: RegimeProbsAI["result"] | null;
  actionBanner: MarketActionAI["result"] | null;
  allocAI: Record<string, { name: string; explanation: string }>;
  recs: SectorRecommendations | null;
  fetchedAt: string | null;
}

const _cache: DashboardCache = {
  regime: null,
  aiResult: null,
  regimeAI: null,
  actionBanner: null,
  allocAI: {},
  recs: null,
  fetchedAt: null,
};

// ---------------------------------------------------------------------------
// AllocationBar (used in collapsible section)
// ---------------------------------------------------------------------------

function AllocationBar({
  label,
  description,
  pct,
  color,
  signalCount,
  isActive,
  healthStatus,
  index = 0,
}: {
  label: string;
  description: string;
  pct: number;
  color: string;
  signalCount?: number;
  isActive?: boolean;
  healthStatus?: string;
  index?: number;
}) {
  const healthBadge = healthStatus && healthStatus !== "healthy" && healthStatus !== "unknown" && healthStatus !== "insufficient_data" ? (
    <span
      className={`inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded-full ${
        healthStatus === "paused"
          ? "bg-rose-500/10 text-rose-400"
          : "bg-amber-500/10 text-amber-400"
      }`}
    >
      {healthStatus === "paused" ? "paused" : "degraded"}
    </span>
  ) : null;

  return (
    <motion.div
      className="mb-2"
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.35, delay: index * 0.05, ease: "easeOut" }}
    >
      <div className="flex justify-between items-center mb-1">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-foreground">
            {label}
          </span>
          {isActive !== undefined && (
            <span
              className={`inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded-full ${
                isActive
                  ? "bg-emerald-500/10 text-emerald-400"
                  : "bg-muted text-foreground/70"
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isActive ? "bg-emerald-400" : "bg-foreground/40"
                }`}
              />
              {isActive
                ? `${signalCount ?? 0} signal${signalCount !== 1 ? "s" : ""}`
                : "no signals"}
            </span>
          )}
          {healthBadge}
        </div>
        <span className="text-[13px] font-bold text-foreground">
          <AnimatedNumber
            value={Math.round(pct * 100)}
            format={(n) => `${Math.round(n)}%`}
          />
        </span>
      </div>
      <div className="h-2 bg-muted/50 rounded-full overflow-hidden">
        <motion.div
          className="h-full rounded-full"
          style={{ background: color }}
          initial={{ width: 0 }}
          animate={{ width: `${pct * 100}%` }}
          transition={{ duration: 0.8, delay: 0.2 + index * 0.05, ease: [0.25, 0.46, 0.45, 0.94] }}
        />
      </div>
      <div className="text-[12px] text-foreground/70 mt-0.5">{description}</div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STRAT_COLORS: Record<string, string> = {
  stat_arb: "#38bdf8",
  catalyst: "#34d399",
  momentum: "#fbbf24",
  flow: "#a78bfa",
  intraday: "#fb7185",
  cash: "#94a3b8",
};

const WEIGHT_KEY_TO_SIGNAL_STRATS: Record<string, string[]> = {
  stat_arb: ["stat_arb"],
  catalyst: ["catalyst_event"],
  momentum: ["cross_asset_momentum", "cross_asset"],
  flow: ["flow_imbalance"],
  intraday: ["gap_reversion"],
};

const WEIGHT_KEY_TO_HEALTH_KEY: Record<string, string> = {
  stat_arb: "stat_arb",
  catalyst: "catalyst",
  momentum: "cross_asset",
  flow: "flow",
  intraday: "intraday",
};

const STRAT_META: Record<string, [string, string]> = {
  stat_arb: ["Pair Trading", "Bets on two similar stocks snapping back together"],
  catalyst: ["Insider & Earnings", "Follows insider buying and earnings surprises"],
  momentum: ["Sector Trends", "Rides sectors that are already going up"],
  flow: ["Big Money Tracking", "Follows what hedge funds are secretly buying"],
  intraday: ["Gap Fills", "Quick trades when stocks open at unusual prices"],
  cash: ["Cash Reserve", "Money kept safe on the sideline"],
};

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function MarketOverviewPage() {
  const hasCached = _cache.regime !== null;
  const [regime, setRegime] = useState<RegimeData | null>(_cache.regime);
  const [aiResult, setAiResult] = useState<AIResult["result"] | null>(_cache.aiResult);
  const [regimeAI, setRegimeAI] = useState<RegimeProbsAI["result"] | null>(_cache.regimeAI);
  const [actionBanner, setActionBanner] = useState<MarketActionAI["result"] | null>(_cache.actionBanner);
  const [allocAI, setAllocAI] = useState<Record<string, { name: string; explanation: string }>>(_cache.allocAI);
  const [loading, setLoading] = useState(!hasCached);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [picksOpen, setPicksOpen] = useState(true);
  const [dashboardFetchedAt, setDashboardFetchedAt] = useState<string | null>(_cache.fetchedAt);

  const recsScan = useSSEScan<SectorRecommendations>(
    "dashboard-recs",
    "/sectors/stream",
    "/sectors/recs-status",
  );
  const recs = recsScan.result;
  const recsLoading = recsScan.isLoading;
  const recsError = recsScan.error;

  const entrySignals: Record<string, EntrySignal> = {};
  const aiTiming = recsScan.aiSummary as { entries?: Array<{ ticker: string; label: string; detail: string; simple?: string; variant: string }> } | null;
  if (aiTiming?.entries) {
    for (const e of aiTiming.entries) {
      const variant = (["green", "amber", "red"].includes(e.variant) ? e.variant : "gray") as BadgeVariant;
      entrySignals[e.ticker] = { ticker: e.ticker, label: e.label, detail: e.detail, simple: e.simple, variant, isAI: true };
    }
  }

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    const r = await apiGet<RegimeData>("/regime/current");
    setRegime(r);
    _cache.regime = r;

    const ts = new Date().toISOString();
    _cache.fetchedAt = ts;
    setDashboardFetchedAt(ts);
    setLoading(false);

    if (r) {
      const aiPromises = Promise.all([
        apiPost<AIResult>("/ai/summarize", { type: "market", data: r }).then((ai) => {
          setAiResult(ai?.result ?? null);
          _cache.aiResult = ai?.result ?? null;
        }),
        apiPost<RegimeProbsAI>("/ai/summarize", {
          type: "regime_probs",
          data: {
            probabilities: r.regime_probabilities,
            vix: r.vix,
            adx: r.adx,
            breadth_pct: r.breadth_pct,
          },
        }).then((regimeProbs) => {
          setRegimeAI(regimeProbs?.result ?? null);
          _cache.regimeAI = regimeProbs?.result ?? null;
        }),
        apiPost<AllocationAI>("/ai/summarize", {
          type: "allocation_explain",
          data: r,
        }).then((allocExplain) => {
          if (allocExplain?.result?.strategies) {
            const map: Record<string, { name: string; explanation: string }> = {};
            for (const s of allocExplain.result.strategies) {
              map[s.key] = { name: s.name, explanation: s.explanation };
            }
            setAllocAI(map);
            _cache.allocAI = map;
          }
        }),
        apiPost<MarketActionAI>("/ai/summarize", {
          type: "market_action",
          data: r,
        }).then((actionAI) => {
          setActionBanner(actionAI?.result ?? null);
          _cache.actionBanner = actionAI?.result ?? null;
        }),
      ]);
      aiPromises.catch(() => {});
    }
  }, []);

  useEffect(() => {
    if (!hasCached) {
      fetchDashboard();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadRecs = useCallback((forceRefresh = false) => {
    recsScan.start("/sectors/start-recs", forceRefresh ? { refresh: 1 } : {});
  }, [recsScan]);

  // ---- Loading state ----
  if (loading) {
    return (
      <>
        <div className="mb-8">
          <div className="h-10 w-64 rounded-xl bg-muted/50 animate-pulse mb-2" />
          <div className="h-5 w-48 rounded-lg bg-muted/30 animate-pulse" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 mb-10">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="rounded-2xl p-[2px] gradient-border opacity-30">
              <div className="rounded-[14px] bg-background p-6 h-28 animate-pulse" />
            </div>
          ))}
        </div>
      </>
    );
  }

  // ---- Offline state ----
  if (!regime) {
    return (
      <>
        <div className="mb-8">
          <h1 className="text-3xl font-black text-foreground tracking-tight">Market Overview</h1>
        </div>
        <GradientCard>
          <div className="text-center py-6">
            <div className="text-amber-400 text-lg font-semibold mb-2">
              Backend Offline
            </div>
            <p className="text-foreground/80 text-sm">
              Start the API with{" "}
              <code className="font-mono bg-muted px-2 py-0.5 rounded-md text-foreground/80">
                uvicorn backend.main:app
              </code>
            </p>
          </div>
        </GradientCard>
      </>
    );
  }

  // ---- Data extraction ----
  const regimeName = regime.regime
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
  const vix = regime.vix;
  const breadth = regime.breadth_pct;
  const adx = regime.adx;
  const confidence = regime.confidence;
  const weights = regime.strategy_weights;
  const probs = regime.regime_probabilities;
  const invested = Object.entries(weights)
    .filter(([k]) => k !== "cash")
    .reduce((sum, [, v]) => sum + v, 0);

  const picks = recs?.stock_picks ?? [];

  const topProb = probs
    ? Object.entries(probs).sort(([, a], [, b]) => b - a)[0]
    : null;

  // ---- Metric configs ----
  const regimeColor =
    regime.regime.includes("bull") ? "#10b981"
    : regime.regime.includes("crisis") ? "#f43f5e"
    : regime.regime.includes("bear") ? "#f59e0b"
    : "#8b5cf6";

  const heroMetrics = [
    {
      label: "Regime",
      value: regimeName,
      valueColor: regimeColor,
      delta: `${Math.round(confidence * 100)}% confidence`,
      deltaColor: (confidence >= 0.6 ? "green" : "neutral") as "green" | "red" | "neutral",
      tooltip: <MetricTooltip content={METRIC_TOOLTIPS.regime} />,
    },
    {
      label: "VIX (Fear Index)",
      value: vix.toFixed(1),
      valueColor: vix >= 30 ? "#f43f5e" : vix >= 20 ? "#f59e0b" : "#10b981",
      delta:
        vix >= 30 ? "High fear — market is panicking"
        : vix >= 20 ? "Elevated — investors are nervous"
        : vix >= 15 ? "Normal — calm market"
        : "Very low — market is complacent",
      deltaColor: (vix >= 25 ? "red" : vix >= 20 ? "neutral" : "green") as "green" | "red" | "neutral",
      tooltip: <MetricTooltip content={METRIC_TOOLTIPS.vix} />,
    },
    {
      label: "Breadth",
      value: `${breadth.toFixed(1)}%`,
      valueColor: breadth >= 60 ? "#10b981" : breadth >= 40 ? "#f59e0b" : "#f43f5e",
      delta:
        breadth >= 70 ? "Strong — most stocks are healthy"
        : breadth >= 50 ? "Mixed — half the market is weak"
        : breadth >= 30 ? "Weak — majority of stocks falling"
        : "Very weak — broad selloff",
      deltaColor: (breadth >= 60 ? "green" : breadth >= 40 ? "neutral" : "red") as "green" | "red" | "neutral",
      tooltip: <MetricTooltip content={METRIC_TOOLTIPS.breadth} />,
    },
    {
      label: "ADX (Trend Strength)",
      value: adx.toFixed(1),
      valueColor: adx >= 25 ? "#3b82f6" : "#64748b",
      delta:
        adx >= 40 ? "Very strong trend"
        : adx >= 25 ? "Clear trend in place"
        : "No clear direction — choppy",
      deltaColor: (adx >= 25 ? "green" : "neutral") as "green" | "red" | "neutral",
      tooltip: <MetricTooltip content={METRIC_TOOLTIPS.adx} />,
    },
  ];

  return (
    <>
      {/* Hero Header */}
      <motion.div
        className="mb-8 flex flex-col sm:flex-row sm:items-center justify-between gap-4"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <div>
          <h1 className="text-2xl font-black tracking-tight">
            <span className="bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] bg-clip-text text-transparent">
              Market Overview
            </span>
          </h1>
          <p className="text-foreground/80 text-[14px] mt-0.5">Your daily market briefing</p>
        </div>
        <div className="flex items-center gap-3">
          {dashboardFetchedAt && !loading && (
            <CacheAge timestamp={dashboardFetchedAt} />
          )}
          <GradientButton
            onClick={fetchDashboard}
            disabled={loading}
          >
            {loading && <PulseInline />}
            {loading ? "Refreshing..." : "Refresh"}
          </GradientButton>
        </div>
      </motion.div>

      {/* Market Action Banner */}
      {actionBanner && (
        <MarketActionBanner
          tone={actionBanner.tone}
          headline={actionBanner.headline}
          detail={actionBanner.detail}
        />
      )}

      {/* Hero Metrics — animated gradient borders */}
      <HeroMetrics metrics={heroMetrics} />

      {/* AI Briefing */}
      {aiResult?.market_summary && (
        <AICard title="Market Briefing" accentColor="#00ccb1">
          <p>{aiResult.market_summary}</p>
          {aiResult.strategy_advice && (
            <div className="mt-3 px-4 py-3 bg-emerald-500/5 rounded-xl text-[13px] text-foreground/80 border border-emerald-500/10">
              <span className="font-semibold text-emerald-400">Strategy:</span>{" "}
              {aiResult.strategy_advice}
            </div>
          )}
        </AICard>
      )}

      {/* Collapsible Details */}
      <motion.div
        className="relative mt-6 rounded-[1.25rem] border-[0.75px] border-border p-2 md:p-3 md:rounded-[1.5rem]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.3 }}
      >
        <GlowingEffect
          spread={40}
          glow
          disabled={false}
          proximity={64}
          inactiveZone={0.01}
          borderWidth={2}
        />
        <button
          onClick={() => setDetailsOpen(!detailsOpen)}
          className="relative flex items-center justify-between w-full rounded-xl border-[0.75px] border-border bg-background px-5 py-3 cursor-pointer active:scale-[0.99] shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]"
        >
          <span className="text-[14px] font-semibold text-foreground">
            Regime Probabilities & Recommended Allocation
          </span>
          <motion.div
            animate={{ rotate: detailsOpen ? 180 : 0 }}
            transition={{ duration: 0.2 }}
          >
            <ChevronDown className="h-4 w-4 text-foreground/80" />
          </motion.div>
        </button>
      </motion.div>

      <AnimatePresence>
        {detailsOpen && (
          <motion.div
            className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
          >
            {/* Regime Probabilities */}
            {probs && Object.keys(probs).length > 0 && (
              <GradientCard animate={false}>
                <h3 className="text-[15px] font-semibold text-foreground mb-3">
                  Regime Probabilities
                </h3>
                <div className="space-y-2.5">
                  {Object.entries(probs)
                    .sort(([, a], [, b]) => b - a)
                    .map(([key, prob], i) => {
                      const label = key
                        .replace(/_/g, " ")
                        .replace(/\b\w/g, (c) => c.toUpperCase());
                      const barColor =
                        prob >= 0.35 ? "#fb7185"
                        : prob >= 0.2 ? "#fbbf24"
                        : "#34d399";
                      return (
                        <div key={key}>
                          <div className="flex justify-between text-[13px] mb-1">
                            <span className="text-foreground/80 font-medium">{label}</span>
                            <span className="font-bold text-foreground">
                              <AnimatedNumber
                                value={Math.round(prob * 100)}
                                format={(n) => `${Math.round(n)}%`}
                              />
                            </span>
                          </div>
                          <div className="h-2 bg-muted/50 rounded-full overflow-hidden">
                            <motion.div
                              className="h-full rounded-full"
                              style={{ background: barColor }}
                              initial={{ width: 0 }}
                              animate={{ width: `${prob * 100}%` }}
                              transition={{ duration: 0.7, delay: 0.15 + i * 0.06, ease: [0.25, 0.46, 0.45, 0.94] }}
                            />
                          </div>
                        </div>
                      );
                    })}
                </div>

                {regimeAI?.action ? (
                  <div className="mt-3 pt-3 border-t border-border space-y-2">
                    <div className="text-[13px] font-semibold text-foreground leading-relaxed">{regimeAI.action}</div>
                    {regimeAI.timing && (
                      <div className="px-3 py-2 bg-emerald-500/5 rounded-lg text-[13px] text-foreground/80 leading-relaxed border border-emerald-500/10">
                        <span className="font-semibold text-emerald-400">When to buy:</span>{" "}
                        {regimeAI.timing}
                      </div>
                    )}
                    {regimeAI.news_sentiment && (
                      <div className="px-3 py-2 bg-amber-500/5 rounded-lg text-[13px] text-foreground/80 leading-relaxed border-l-2 border-amber-500/40">
                        <span className="font-semibold text-amber-400">Market Mood:</span>{" "}
                        {regimeAI.news_sentiment}
                      </div>
                    )}
                  </div>
                ) : topProb ? (
                  <div className="mt-3 pt-3 border-t border-border">
                    <div className="text-[13px] text-foreground/80 leading-relaxed">
                      Top scenario:{" "}
                      <span className="font-medium text-foreground">
                        {topProb[0].replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                      </span>{" "}
                      ({Math.round(topProb[1] * 100)}%).{" "}
                      {topProb[1] >= 0.5 ? "System is confident." : "System is unsure — keeping extra cash."}
                    </div>
                  </div>
                ) : null}
              </GradientCard>
            )}

            {/* Strategy Allocation */}
            {weights && Object.keys(weights).length > 0 && (
              <GradientCard animate={false}>
                <h3 className="text-[15px] font-semibold text-foreground mb-1">
                  Recommended Allocation
                </h3>
                <p className="text-[12px] text-foreground/80 mb-3">
                  Based on today&apos;s market conditions, here&apos;s how you should split your money if investing right now.
                </p>

                <AllocationDonut
                  slices={Object.entries(weights)
                    .sort(([, a], [, b]) => b - a)
                    .filter(([, v]) => v >= 0.01)
                    .map(([key, pct]) => {
                      const [fallbackName] = STRAT_META[key] ?? [
                        key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
                      ];
                      return {
                        key,
                        label: allocAI[key]?.name ?? fallbackName,
                        value: pct,
                        color: STRAT_COLORS[key] ?? "#64748b",
                      };
                    })}
                  investedPct={invested}
                  className="mb-4"
                />

                <div>
                  {Object.entries(weights)
                    .sort(([, a], [, b]) => b - a)
                    .filter(([, v]) => v >= 0.01)
                    .map(([key, pct], i) => {
                      const ai = allocAI[key];
                      const [fallbackName, fallbackDesc] = STRAT_META[key] ?? [
                        key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
                        "",
                      ];
                      const activity = regime?.strategy_activity;
                      const signalStrats = WEIGHT_KEY_TO_SIGNAL_STRATS[key];
                      let signalCount: number | undefined;
                      let isActive: boolean | undefined;
                      if (activity && signalStrats) {
                        signalCount = 0;
                        for (const sk of signalStrats) {
                          signalCount += activity[sk]?.signal_count ?? 0;
                        }
                        isActive = signalCount > 0;
                      }
                      const healthKey = WEIGHT_KEY_TO_HEALTH_KEY[key];
                      const health = healthKey ? regime?.strategy_health?.[healthKey] : undefined;

                      return (
                        <AllocationBar
                          key={key}
                          label={ai?.name ?? fallbackName}
                          description={ai?.explanation ?? fallbackDesc}
                          pct={pct}
                          color={STRAT_COLORS[key] ?? "#64748b"}
                          signalCount={signalCount}
                          isActive={isActive}
                          healthStatus={health?.status}
                          index={i}
                        />
                      );
                    })}
                </div>
                <div className="mt-3 pt-3 border-t border-border text-[13px] text-foreground/80 leading-relaxed">
                  {invested >= 0.8 ? (
                    <p>
                      <strong className="text-emerald-400">Go all in.</strong> Market conditions look
                      favorable — put {Math.round(invested * 100)}% to work
                      and keep just {Math.round((1 - invested) * 100)}% as a safety buffer.
                    </p>
                  ) : invested >= 0.5 ? (
                    <p>
                      <strong className="text-cyan-400">Be cautious.</strong> Invest{" "}
                      {Math.round(invested * 100)}% of your capital, keep{" "}
                      {Math.round((1 - invested) * 100)}% in cash.
                      {regime.regime.includes("bear")
                        ? " Downtrend — cash lets you buy cheaper later."
                        : " Uncertain — keep flexibility for better opportunities."}
                    </p>
                  ) : invested >= 0.2 ? (
                    <p>
                      <strong className="text-amber-400">Stay mostly in cash.</strong> Only invest{" "}
                      {Math.round(invested * 100)}%, hold {Math.round((1 - invested) * 100)}% in cash.
                      The market looks risky.
                    </p>
                  ) : (
                    <p>
                      <strong className="text-rose-400">Wait it out.</strong> Too risky right now.
                      Keep most of your money in cash.
                    </p>
                  )}
                </div>
              </GradientCard>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Stock Picks Toggle */}
      <motion.div
        className="relative mt-8 rounded-[1.25rem] border-[0.75px] border-border p-2 md:p-3 mb-5 md:rounded-[1.5rem]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.2 }}
      >
        <GlowingEffect
          spread={40}
          glow
          disabled={false}
          proximity={64}
          inactiveZone={0.01}
          borderWidth={2}
        />
        <div className="relative flex items-center w-full rounded-xl border-[0.75px] border-border bg-background px-5 py-3 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
          <span className="text-[14px] font-semibold text-foreground">Stock Picks</span>
          <div className="flex items-center gap-2 ml-auto mr-3">
            {recsScan.resultTimestamp && !recsLoading && (
              <CacheAge timestamp={recsScan.resultTimestamp} />
            )}
            <GradientButton
              onClick={() => loadRecs(false)}
              disabled={recsLoading}
            >
              {recsLoading && <PulseInline />}
              {recsLoading ? "Analyzing..." : recs ? "Reload Picks" : "Load Stock Picks"}
            </GradientButton>
            {recs && !recsLoading && (
              <GradientButton onClick={() => loadRecs(true)}>
                Force Refresh
              </GradientButton>
            )}
          </div>
          <button
            onClick={() => setPicksOpen(!picksOpen)}
            className="cursor-pointer"
          >
            <motion.div
              animate={{ rotate: picksOpen ? 180 : 0 }}
              transition={{ duration: 0.2 }}
            >
              <ChevronDown className="h-4 w-4 text-foreground/80" />
            </motion.div>
          </button>
        </div>
      </motion.div>

      <AnimatePresence>
        {picksOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
          >

      {/* Stock Picks Loading / Error */}
      {recsLoading && (
        <GradientCard animate={false}>
          <div className="py-6">
            <PulseLoader
              size="lg"
              label={`Analyzing sectors... ${recsScan.total > 0 ? Math.round((recsScan.progress / recsScan.total) * 100) : 0}%`}
              progress={recsScan.total > 0 ? Math.round((recsScan.progress / recsScan.total) * 100) : undefined}
              sublabel={recsScan.step || "Scanning every S&P 500 sector and evaluating top stocks."}
            />
          </div>
        </GradientCard>
      )}

      {recsError && !recsLoading && (
        <GradientCard animate={false}>
          <div className="text-center py-4">
            <div className="text-[15px] font-semibold text-rose-400 mb-1">
              Could not load stock picks
            </div>
            <p className="text-[13px] text-foreground/80">{recsError}</p>
            <button
              onClick={() => loadRecs(false)}
              className="mt-3 px-4 py-2 border border-border rounded-xl text-sm font-medium text-foreground/80 hover:text-foreground transition-all active:scale-[0.98] cursor-pointer"
            >
              Try Again
            </button>
          </div>
        </GradientCard>
      )}

      {/* Stock Picks */}
      {picks.length > 0 && !recsLoading && (
        <div>
          {picks.slice(0, 5).map((p, i) => {
            const scoreVariant: BadgeVariant =
              p.score >= 70 ? "green" : p.score >= 50 ? "amber" : "red";
            const entry = p.entry ?? p.price;
            const stop = p.stop_loss ?? 0;
            const target = p.target ?? Math.round(entry * 1.3 * 100) / 100;
            const aiSignal = entrySignals[p.ticker];
            const signal: EntrySignal = aiSignal ?? fallbackEntrySignal(
              p.ticker, p.price, entry, stop, target, p.rsi
            );
            const rr =
              stop && entry && target
                ? (Math.abs(target - entry) / Math.abs(entry - stop)).toFixed(1)
                : null;

            return (
              <TradeCard
                key={p.ticker}
                ticker={p.ticker}
                name={p.name}
                rank={i + 1}
                price={p.price}
                index={i}
                badges={[
                  { text: p.sector, variant: "blue" },
                  { text: `Score ${p.score}`, variant: scoreVariant },
                ]}
                stats={[
                  { label: "Entry", value: formatDollar(entry) },
                  { label: "Stop Loss", value: stop ? formatDollar(stop) : "—", color: "#f43f5e" },
                  { label: "Target", value: formatDollar(target), color: "#10b981" },
                  ...(rr ? [{ label: "R/R", value: `${rr}:1` }] : []),
                  ...(p.rsi ? [{ label: "RSI", value: p.rsi.toFixed(0) }] : []),
                ]}
                entrySignal={signal}
                meta={p.why}
              />
            );
          })}
        </div>
      )}

      {/* Sector Breakdown */}
      {recs?.sectors && recs.sectors.length > 0 && !recsLoading && (
        <motion.div
          className="mt-8"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <h3 className="text-xl font-bold text-foreground mb-4">Sector Breakdown</h3>
          <SectorTable sectors={recs.sectors} />
        </motion.div>
      )}

          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
