"use client";

import { useEffect, useState, useCallback } from "react";
import { PulseLoader, PulseInline } from "@/components/pulse-loader";
import { PageHeader } from "@/components/page-header";
import { MetricCard } from "@/components/metric-card";
import { AICard } from "@/components/ai-card";
import { TradeCard } from "@/components/trade-card";
import { Badge } from "@/components/badge";
import { MarketActionBanner } from "@/components/market-action-banner";
import { CacheAge } from "@/components/cache-age";
import { apiGet, apiPost } from "@/lib/api";
import { formatDollar } from "@/lib/utils";
import { fallbackEntrySignal, type EntrySignal } from "@/lib/entry-timing";
import type {
  RegimeData,
  AIResult,
  SectorRecommendations,
  BadgeVariant,
} from "@/lib/types";

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

interface EntryTimingAI {
  result: {
    entries: Array<{
      ticker: string;
      label: string;
      detail: string;
      simple?: string;
      variant: "green" | "amber" | "red";
    }>;
  } | null;
}

// ---------------------------------------------------------------------------
// Module-level cache — survives React navigation / remounts so the dashboard
// loads instantly when you come back instead of refetching 4 AI calls.
// ---------------------------------------------------------------------------
interface DashboardCache {
  regime: RegimeData | null;
  aiResult: AIResult["result"] | null;
  regimeAI: RegimeProbsAI["result"] | null;
  actionBanner: MarketActionAI["result"] | null;
  allocAI: Record<string, { name: string; explanation: string }>;
  recs: SectorRecommendations | null;
  recsCacheAge: number | null;
  entrySignals: Record<string, EntrySignal>;
  fetchedAt: string | null;
}

const _cache: DashboardCache = {
  regime: null,
  aiResult: null,
  regimeAI: null,
  actionBanner: null,
  allocAI: {},
  recs: null,
  recsCacheAge: null,
  entrySignals: {},
  fetchedAt: null,
};

function AllocationBar({
  label,
  description,
  pct,
  color,
}: {
  label: string;
  description: string;
  pct: number;
  color: string;
}) {
  return (
    <div className="mb-3">
      <div className="flex justify-between items-center mb-1">
        <span className="text-[13px] font-semibold text-text-primary">
          {label}
        </span>
        <span className="text-[13px] font-bold font-mono text-text-primary">
          {Math.round(pct * 100)}%
        </span>
      </div>
      <div className="h-2 bg-card-alt rounded-full border border-border overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct * 100}%`, background: color }}
        />
      </div>
      <div className="text-[12px] text-text-muted mt-0.5">{description}</div>
    </div>
  );
}

const STRAT_COLORS: Record<string, string> = {
  stat_arb: "#3b7dd8",
  catalyst: "#539616",
  momentum: "#c6a339",
  flow: "#6c5ce7",
  intraday: "#d44040",
  cash: "#a6a6a0",
};

const STRAT_META: Record<string, [string, string]> = {
  stat_arb: ["Pair Trading", "Bets on two similar stocks snapping back together"],
  catalyst: ["Insider & Earnings", "Follows insider buying and earnings surprises"],
  momentum: ["Sector Trends", "Rides sectors that are already going up"],
  flow: ["Big Money Tracking", "Follows what hedge funds are secretly buying"],
  intraday: ["Gap Fills", "Quick trades when stocks open at unusual prices"],
  cash: ["Cash Reserve", "Money kept safe on the sideline"],
};

export default function MarketOverviewPage() {
  const hasCached = _cache.regime !== null;
  const [regime, setRegime] = useState<RegimeData | null>(_cache.regime);
  const [aiResult, setAiResult] = useState<AIResult["result"] | null>(_cache.aiResult);
  const [regimeAI, setRegimeAI] = useState<RegimeProbsAI["result"] | null>(_cache.regimeAI);
  const [actionBanner, setActionBanner] = useState<MarketActionAI["result"] | null>(_cache.actionBanner);
  const [allocAI, setAllocAI] = useState<Record<string, { name: string; explanation: string }>>(_cache.allocAI);
  const [recs, setRecs] = useState<SectorRecommendations | null>(_cache.recs);
  const [entrySignals, setEntrySignals] = useState<Record<string, EntrySignal>>(_cache.entrySignals);
  const [loading, setLoading] = useState(!hasCached);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [recsLoading, setRecsLoading] = useState(false);
  const [recsError, setRecsError] = useState<string | null>(null);
  const [recsCacheAge, setRecsCacheAge] = useState<number | null>(_cache.recsCacheAge);
  const [dashboardFetchedAt, setDashboardFetchedAt] = useState<string | null>(_cache.fetchedAt);

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    const r = await apiGet<RegimeData>("/regime/current");
    setRegime(r);
    _cache.regime = r;

    if (r) {
      const [ai, regimeProbs, allocExplain, actionAI] = await Promise.all([
        apiPost<AIResult>("/ai/summarize", { type: "market", data: r }),
        apiPost<RegimeProbsAI>("/ai/summarize", {
          type: "regime_probs",
          data: {
            probabilities: r.regime_probabilities,
            vix: r.vix,
            adx: r.adx,
            breadth_pct: r.breadth_pct,
          },
        }),
        apiPost<AllocationAI>("/ai/summarize", {
          type: "allocation_explain",
          data: r,
        }),
        apiPost<MarketActionAI>("/ai/summarize", {
          type: "market_action",
          data: r,
        }),
      ]);
      setAiResult(ai?.result ?? null);
      setRegimeAI(regimeProbs?.result ?? null);
      setActionBanner(actionAI?.result ?? null);
      _cache.aiResult = ai?.result ?? null;
      _cache.regimeAI = regimeProbs?.result ?? null;
      _cache.actionBanner = actionAI?.result ?? null;

      if (allocExplain?.result?.strategies) {
        const map: Record<string, { name: string; explanation: string }> = {};
        for (const s of allocExplain.result.strategies) {
          map[s.key] = { name: s.name, explanation: s.explanation };
        }
        setAllocAI(map);
        _cache.allocAI = map;
      }
    }

    const ts = new Date().toISOString();
    _cache.fetchedAt = ts;
    setDashboardFetchedAt(ts);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!hasCached) {
      fetchDashboard();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadRecs = useCallback(async (forceRefresh = false) => {
    setRecsLoading(true);
    setRecsError(null);
    setEntrySignals({});
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 600_000);

      const API_BASE =
        process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
      const url = `${API_BASE}/sectors/recommendations${forceRefresh ? "?refresh=true" : ""}`;
      const res = await fetch(url, {
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
      });
      clearTimeout(timeoutId);

      if (!res.ok) {
        setRecsError(`API returned ${res.status}`);
        setRecsLoading(false);
        return;
      }

      const raw = await res.json();
      const data: SectorRecommendations = raw;
      setRecs(data);
      setRecsCacheAge(raw.cache_age_minutes ?? null);
      _cache.recs = data;
      _cache.recsCacheAge = raw.cache_age_minutes ?? null;

      // Ask AI for entry timing on top picks
      const topPicks = (data.stock_picks ?? []).slice(0, 5);
      if (topPicks.length > 0) {
        const currentRegime = regime?.regime ?? "unknown";
        const timingRes = await apiPost<EntryTimingAI>("/ai/summarize", {
          type: "entry_timing",
          data: {
            regime: currentRegime,
            picks: topPicks.map((p) => ({
              ticker: p.ticker,
              name: p.name,
              sector: p.sector,
              price: p.price,
              entry: p.entry ?? p.price,
              stop_loss: p.stop_loss ?? 0,
              target: p.target ?? 0,
              rsi: p.rsi,
              why: p.why,
            })),
          },
        });

        if (timingRes?.result?.entries && Array.isArray(timingRes.result.entries)) {
          const map: Record<string, EntrySignal> = {};
          for (const e of timingRes.result.entries) {
            const variant = (["green", "amber", "red"].includes(e.variant)
              ? e.variant
              : "gray") as BadgeVariant;
            map[e.ticker] = {
              ticker: e.ticker,
              label: e.label,
              detail: e.detail,
              simple: e.simple,
              variant,
              isAI: true,
            };
          }
          setEntrySignals(map);
          _cache.entrySignals = map;
        } else {
          console.warn("[EntryTiming] AI returned no entries:", timingRes);
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setRecsError("Request timed out. The backend may still be processing.");
      } else {
        setRecsError("Failed to load. Is the backend running?");
      }
    } finally {
      setRecsLoading(false);
    }
  }, [regime]);

  if (loading) {
    return (
      <>
        <PageHeader
          title="Market Overview"
          subtitle="Regime detection, strategy allocation & sector recommendations"
        />
        <div className="grid grid-cols-4 gap-4 mb-8">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="bg-card border border-border rounded-2xl px-5 py-4 animate-qp-pulse"
              style={{ boxShadow: "var(--shadow-card)" }}
            >
              <div className="h-3 bg-border rounded w-16 mb-3" />
              <div className="h-7 bg-border rounded w-24" />
            </div>
          ))}
        </div>
      </>
    );
  }

  if (!regime) {
    return (
      <>
        <PageHeader title="Market Overview" />
        <div
          className="bg-card border border-border rounded-2xl px-8 py-10 text-center"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <div className="text-qp-amber text-lg font-semibold mb-2">
            Backend Offline
          </div>
          <p className="text-text-secondary text-sm">
            Start the API with{" "}
            <code className="font-mono bg-card-alt px-2 py-0.5 rounded-md border border-border text-text-body">
              uvicorn backend.main:app
            </code>
          </p>
        </div>
      </>
    );
  }

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

  return (
    <>
      <PageHeader
        title="Market Overview"
        subtitle="Your daily market briefing"
        description="This page shows you what the market is doing right now — is it going up, down, or sideways? Based on that, it tells you which strategies work best today and picks the top stocks to look at. Click 'Load Stock Picks' to get specific buy recommendations with entry prices and targets."
        actions={
          <div className="flex items-center gap-2">
            {dashboardFetchedAt && !loading && (
              <CacheAge timestamp={dashboardFetchedAt} />
            )}
            <button
              onClick={fetchDashboard}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2.5 border border-border rounded-xl text-sm font-medium text-text-body hover:bg-card-alt transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loading && <PulseInline />}
              {loading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        }
      />

      {/* Market Action Banner */}
      {actionBanner && (
        <MarketActionBanner
          tone={actionBanner.tone}
          headline={actionBanner.headline}
          detail={actionBanner.detail}
        />
      )}

      {/* Top Metrics */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <MetricCard
          label="Regime"
          value={regimeName}
          valueColor={
            regime.regime.includes("bull") ? "#2d9d3a"
            : regime.regime.includes("crisis") ? "#d44040"
            : regime.regime.includes("bear") ? "#c68a1a"
            : "#6c5ce7"
          }
          delta={`${Math.round(confidence * 100)}% confidence`}
          deltaColor={confidence >= 0.6 ? "green" : "neutral"}
        />
        <MetricCard
          label="VIX (Fear Index)"
          value={vix.toFixed(1)}
          valueColor={vix >= 30 ? "#d44040" : vix >= 20 ? "#c68a1a" : "#2d9d3a"}
          delta={
            vix >= 30 ? "High fear — market is panicking"
            : vix >= 20 ? "Elevated — investors are nervous"
            : vix >= 15 ? "Normal — calm market"
            : "Very low — market is complacent"
          }
          deltaColor={vix >= 25 ? "red" : vix >= 20 ? "neutral" : "green"}
        />
        <MetricCard
          label="Breadth"
          value={`${breadth.toFixed(1)}%`}
          valueColor={breadth >= 60 ? "#2d9d3a" : breadth >= 40 ? "#c68a1a" : "#d44040"}
          delta={
            breadth >= 70 ? "Strong — most stocks are healthy"
            : breadth >= 50 ? "Mixed — half the market is weak"
            : breadth >= 30 ? "Weak — majority of stocks falling"
            : "Very weak — broad selloff"
          }
          deltaColor={breadth >= 60 ? "green" : breadth >= 40 ? "neutral" : "red"}
        />
        <MetricCard
          label="ADX (Trend Strength)"
          value={adx.toFixed(1)}
          valueColor={adx >= 25 ? "#3b7dd8" : "#a6a6a0"}
          delta={
            adx >= 40 ? "Very strong trend"
            : adx >= 25 ? "Clear trend in place"
            : "No clear direction — choppy"
          }
          deltaColor={adx >= 25 ? "green" : "neutral"}
        />
      </div>

      {/* AI Briefing */}
      {aiResult?.market_summary && (
        <AICard title="Market Briefing" accentColor="#539616">
          <p>{aiResult.market_summary}</p>
          {aiResult.strategy_advice && (
            <div className="mt-3 px-4 py-3 bg-accent-bg rounded-xl text-[13px] text-text-body">
              <span className="font-semibold text-accent">Strategy:</span>{" "}
              {aiResult.strategy_advice}
            </div>
          )}
        </AICard>
      )}

      {/* Collapsible Details */}
      <button
        onClick={() => setDetailsOpen(!detailsOpen)}
        className="mt-6 w-full flex items-center justify-between px-5 py-3 bg-card border border-border rounded-xl hover:bg-card-alt transition-colors"
        style={{ boxShadow: "var(--shadow-card)" }}
      >
        <span className="text-[14px] font-semibold text-text-primary">
          Regime Probabilities & Recommended Allocation
        </span>
        <span className="text-text-muted text-lg">
          {detailsOpen ? "▲" : "▼"}
        </span>
      </button>

      {detailsOpen && (
      <div className="grid grid-cols-2 gap-6 mt-3">
        {/* Regime Probabilities */}
        {probs && Object.keys(probs).length > 0 && (
          <div
            className="bg-card border border-border rounded-2xl px-6 py-5"
            style={{ boxShadow: "var(--shadow-card)" }}
          >
            <h3 className="text-[15px] font-semibold text-text-primary mb-4">
              Regime Probabilities
            </h3>
            <div className="space-y-3">
              {Object.entries(probs)
                .sort(([, a], [, b]) => b - a)
                .map(([key, prob]) => {
                  const label = key
                    .replace(/_/g, " ")
                    .replace(/\b\w/g, (c) => c.toUpperCase());
                  const barColor =
                    prob >= 0.35
                      ? "#d44040"
                      : prob >= 0.2
                        ? "#c6a339"
                        : "#539616";
                  return (
                    <div key={key}>
                      <div className="flex justify-between text-[13px] mb-1">
                        <span className="text-text-body font-medium">
                          {label}
                        </span>
                        <span className="font-mono font-bold text-text-primary">
                          {Math.round(prob * 100)}%
                        </span>
                      </div>
                      <div className="h-2 bg-card-alt rounded-full border border-border overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{
                            width: `${prob * 100}%`,
                            background: barColor,
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
            </div>

            {/* AI Regime Analysis */}
            {regimeAI?.action ? (
              <div className="mt-5 pt-4 border-t border-border space-y-2">
                <div className="text-[14px] font-semibold text-text-primary">
                  {regimeAI.action}
                </div>
                {regimeAI.timing && (
                  <div className="px-3 py-2.5 bg-accent-bg rounded-xl text-[13px] text-text-body">
                    <span className="font-semibold text-accent">
                      When to buy:
                    </span>{" "}
                    {regimeAI.timing}
                  </div>
                )}
                {regimeAI.news_sentiment && (
                  <div
                    className="px-3 py-2.5 bg-qp-amber-bg rounded-xl text-[13px] text-text-body"
                    style={{ borderLeft: "3px solid #c6a339" }}
                  >
                    <span className="font-semibold text-qp-amber">
                      Market Mood:
                    </span>{" "}
                    {regimeAI.news_sentiment}
                  </div>
                )}
              </div>
            ) : topProb ? (
              <div className="mt-4 pt-3 border-t border-border">
                <div className="text-[13px] text-text-secondary">
                  Top scenario:{" "}
                  <span className="font-medium text-text-primary">
                    {topProb[0]
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (c) => c.toUpperCase())}
                  </span>{" "}
                  ({Math.round(topProb[1] * 100)}%).{" "}
                  {topProb[1] >= 0.5
                    ? "System is confident."
                    : "System is unsure — keeping extra cash."}
                </div>
              </div>
            ) : null}
          </div>
        )}

        {/* Strategy Allocation */}
        {weights && Object.keys(weights).length > 0 && (
          <div
            className="bg-card border border-border rounded-2xl px-6 py-5"
            style={{ boxShadow: "var(--shadow-card)" }}
          >
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-[15px] font-semibold text-text-primary">
                Recommended Allocation
              </h3>
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-2xl font-bold text-accent">
                  {Math.round(invested * 100)}%
                </span>
                <span className="text-[12px] text-text-muted">in market</span>
              </div>
            </div>
            <p className="text-[12px] text-text-muted mb-4">
              Based on today&apos;s market conditions, here&apos;s how you should split your money if investing right now.
            </p>
            <div>
              {Object.entries(weights)
                .sort(([, a], [, b]) => b - a)
                .filter(([, v]) => v >= 0.01)
                .map(([key, pct]) => {
                  const ai = allocAI[key];
                  const [fallbackName, fallbackDesc] = STRAT_META[key] ?? [
                    key
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (c) => c.toUpperCase()),
                    "",
                  ];
                  return (
                    <AllocationBar
                      key={key}
                      label={ai?.name ?? fallbackName}
                      description={ai?.explanation ?? fallbackDesc}
                      pct={pct}
                      color={STRAT_COLORS[key] ?? "#a6a6a0"}
                    />
                  );
                })}
            </div>
            <div className="mt-3 pt-3 border-t border-border text-[13px] text-text-body leading-relaxed">
              {invested >= 0.8 ? (
                <p>
                  <strong className="text-qp-green">Go all in.</strong> Market conditions look
                  favorable — if you&apos;re investing, put {Math.round(invested * 100)}% to work
                  and keep just {Math.round((1 - invested) * 100)}% as a safety buffer.
                </p>
              ) : invested >= 0.5 ? (
                <p>
                  <strong className="text-accent">Be cautious.</strong> The recommendation is to
                  invest {Math.round(invested * 100)}% of your capital and keep{" "}
                  {Math.round((1 - invested) * 100)}% in cash.
                  {regime.regime.includes("bear")
                    ? " The market is in a downtrend right now, so having cash on hand lets you buy cheaper later if stocks keep falling."
                    : " The market is uncertain, so keeping some cash gives you flexibility to jump on better opportunities."}
                </p>
              ) : invested >= 0.2 ? (
                <p>
                  <strong className="text-qp-amber">Stay mostly in cash.</strong> The recommendation
                  is to only invest {Math.round(invested * 100)}% and hold{" "}
                  {Math.round((1 - invested) * 100)}% in cash. The market looks risky — it&apos;s
                  better to protect your money now and invest more when conditions improve.
                </p>
              ) : (
                <p>
                  <strong className="text-qp-red">Wait it out.</strong> The market looks too
                  risky to invest right now. Keep most of your money in cash and wait for
                  things to stabilize.
                </p>
              )}
            </div>
          </div>
        )}
      </div>
      )}

      {/* Stock Picks Header */}
      <div className="mt-8 flex items-center justify-between mb-4">
        <h3 className="text-[18px] font-bold text-text-primary">
          Stock Picks
        </h3>
        <div className="flex items-center gap-2">
          {recsCacheAge !== null && !recsLoading && (
            <span className="text-[12px] text-text-muted">
              {recsCacheAge < 1
                ? "Just updated"
                : `Updated ${Math.round(recsCacheAge)}m ago`}
            </span>
          )}
          <button
            onClick={() => loadRecs(false)}
            disabled={recsLoading}
            className="flex items-center gap-2 px-5 py-2.5 bg-accent text-white rounded-xl text-sm font-semibold hover:bg-accent-light transition-colors shadow-sm disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {recsLoading && <PulseInline />}
            {recsLoading ? "Analyzing..." : recs ? "Reload Picks" : "Load Stock Picks"}
          </button>
          {recs && !recsLoading && (
            <button
              onClick={() => loadRecs(true)}
              className="px-4 py-2.5 border border-border rounded-xl text-sm font-medium text-text-body hover:bg-card-alt transition-colors"
            >
              Force Refresh
            </button>
          )}
        </div>
      </div>

      {/* Stock Picks Loading / Error States */}
      {recsLoading && (
        <div
          className="mt-8 bg-card border border-border rounded-2xl px-8 py-10 text-center"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <PulseLoader
            size="lg"
            label="Analyzing all sectors and picking top stocks..."
            sublabel="Scanning every S&P 500 sector and evaluating top stocks in each. Usually takes 1-3 minutes."
          />
        </div>
      )}

      {recsError && !recsLoading && (
        <div
          className="mt-8 bg-qp-red-bg border border-qp-red/15 rounded-2xl px-8 py-6 text-center"
        >
          <div className="text-[15px] font-semibold text-qp-red mb-1">
            Could not load stock picks
          </div>
          <p className="text-[13px] text-text-muted">{recsError}</p>
          <button
            onClick={() => loadRecs(false)}
            className="mt-3 px-4 py-2 bg-card border border-border rounded-xl text-sm font-medium text-text-primary hover:bg-card-alt transition-colors"
          >
            Try Again
          </button>
        </div>
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
                badges={[
                  { text: p.sector, variant: "blue" },
                  { text: `Score ${p.score}`, variant: scoreVariant },
                ]}
                stats={[
                  { label: "Entry", value: formatDollar(entry) },
                  {
                    label: "Stop Loss",
                    value: stop ? formatDollar(stop) : "—",
                    color: "#d44040",
                  },
                  {
                    label: "Target",
                    value: formatDollar(target),
                    color: "#2d9d3a",
                  },
                  ...(rr ? [{ label: "R/R", value: `${rr}:1` }] : []),
                  ...(p.rsi
                    ? [{ label: "RSI", value: p.rsi.toFixed(0) }]
                    : []),
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
        <div className="mt-8">
          <h3 className="text-[18px] font-bold text-text-primary mb-4">
            Sector Breakdown
          </h3>
          <div className="grid grid-cols-1 gap-2">
            {recs.sectors.map((s) => {
              const verdictVariant: BadgeVariant =
                s.verdict === "BUY"
                  ? "green"
                  : s.verdict === "HOLD"
                    ? "amber"
                    : "red";
              return (
                <div
                  key={s.sector}
                  className="bg-card border border-border rounded-xl px-5 py-3 flex justify-between items-center"
                  style={{ boxShadow: "var(--shadow-card)" }}
                >
                  <div className="flex items-center gap-3">
                    <span className="text-[14px] font-semibold text-text-primary">
                      {s.sector}
                    </span>
                    <span className="text-[12px] text-text-muted font-mono">
                      {s.etf}
                    </span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span
                      className="font-mono text-[13px] font-medium"
                      style={{
                        color: s.return_5d >= 0 ? "#2d9d3a" : "#d44040",
                      }}
                    >
                      5d: {s.return_5d >= 0 ? "+" : ""}
                      {s.return_5d.toFixed(1)}%
                    </span>
                    <span
                      className="font-mono text-[13px] font-medium"
                      style={{
                        color: s.return_20d >= 0 ? "#2d9d3a" : "#d44040",
                      }}
                    >
                      20d: {s.return_20d >= 0 ? "+" : ""}
                      {s.return_20d.toFixed(1)}%
                    </span>
                    <span className="font-mono text-[12px] text-text-muted">
                      RSI {s.rsi.toFixed(0)}
                    </span>
                    <Badge variant={verdictVariant}>
                      {s.verdict} {s.score}
                    </Badge>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}
