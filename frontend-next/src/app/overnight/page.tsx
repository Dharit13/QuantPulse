"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Moon,
  Sun,
  AlertTriangle,
  BarChart3,
  Bitcoin,
  ChevronDown,
  ChevronUp,
  Trophy,
  TrendingUp,
  TrendingDown,
  Flame,
  Clock,
} from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { GradientCard, GradientButton } from "@/components/gradient-card";
import { GlowingEffect } from "@/components/ui/glowing-effect";
import { SlideUp, StaggerGroup, StaggerItem } from "@/components/motion-primitives";
import { PulseLoader } from "@/components/pulse-loader";
import { CacheAge } from "@/components/cache-age";
import { Badge } from "@/components/badge";
import { useSSEScan } from "@/hooks/use-sse-scan";
import { apiGet, apiPost } from "@/lib/api";
import type { BadgeVariant } from "@/lib/types";

// ── Types ────────────────────────────────────────────────────

interface OvernightPick {
  symbol: string;
  action: "BUY" | "SKIP";
  confidence: number;
  entry_strategy: string;
  exit_strategy: string;
  expected_move_pct: string;
  risk_reward: string;
  reasoning: string;
  key_signals: string[];
  risk_factors: string[];
  position_size_suggestion: string;
  sector?: string;
  liquidity_ok?: boolean;
}

interface MacroRegime {
  summary: string;
  bias: "bullish" | "bearish" | "neutral";
  key_factors: string[];
}

interface OvernightResult {
  scan_timestamp?: string;
  macro_regime?: MacroRegime;
  correlation_warning?: string;
  market_closed_note?: string;
  stock_picks?: OvernightPick[];
  crypto_picks?: OvernightPick[];
  market_summary?: string;
  no_stock_reason?: string;
  no_crypto_reason?: string;
}

type ScanMode = "both" | "stocks" | "crypto";

interface ScorecardData {
  has_data: boolean;
  total_picks: number;
  winners: number;
  losers: number;
  win_rate: number;
  avg_return: number;
  total_return: number;
  best_pick?: { symbol: string; return_pct: number; scan_date: string };
  worst_pick?: { symbol: string; return_pct: number; scan_date: string };
  streak: string;
  calibration: Record<string, { total: number; wins: number; win_rate: number; avg_return: number }>;
  by_type: {
    stocks: { total: number; wins?: number; win_rate?: number; avg_return?: number };
    crypto: { total: number; wins?: number; win_rate?: number; avg_return?: number };
  };
  recent_picks: Array<{
    symbol: string;
    pick_type: string;
    confidence: number;
    entry_price: number;
    exit_price: number;
    return_pct: number;
    won: boolean;
    scan_date: string;
    sector: string;
  }>;
  pending_picks: Array<{
    symbol: string;
    pick_type: string;
    confidence: number;
    entry_price: number;
    scan_date: string;
  }>;
}

const BIAS_CONFIG: Record<string, { color: string; badge: BadgeVariant }> = {
  bullish: { color: "#34d399", badge: "green" },
  bearish: { color: "#fb7185", badge: "red" },
  neutral: { color: "#fbbf24", badge: "amber" },
};

// ── Components ───────────────────────────────────────────────

const CONFIDENCE_COLORS: Record<string, string> = {
  high: "#00ccb1",
  medium: "#38bdf8",
  low: "#fbbf24",
};

function getConfidenceColor(value: number): string {
  if (value >= 80) return CONFIDENCE_COLORS.high;
  if (value >= 65) return CONFIDENCE_COLORS.medium;
  return CONFIDENCE_COLORS.low;
}

function PickCard({ pick, type, rank }: { pick: OvernightPick; type: "stock" | "crypto"; rank: number }) {
  const [expanded, setExpanded] = useState(false);
  const confColor = getConfidenceColor(pick.confidence);

  return (
    <StaggerItem>
      <GradientCard animate={false}>
        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <span
              className="text-xl font-extrabold min-w-[28px]"
              style={{ color: confColor }}
            >
              #{rank}
            </span>
            <span className="text-[17px] font-bold text-foreground">
              {pick.symbol}
            </span>
            {pick.sector && (
              <span className="text-[13px] text-foreground/50">{pick.sector}</span>
            )}
            {pick.liquidity_ok === false && (
              <Badge variant="red">Low Liquidity</Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span
              className="text-[22px] font-bold tabular-nums"
              style={{ color: confColor }}
            >
              {pick.confidence}
            </span>
            <span className="text-[11px] text-foreground/40 font-medium uppercase">/100</span>
          </div>
        </div>

        {/* Confidence bar */}
        <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden mt-3">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${pick.confidence}%`,
              background: `linear-gradient(90deg, ${confColor}, ${confColor}88)`,
            }}
          />
        </div>

        {/* Stats row */}
        <div className="flex gap-6 mt-4 flex-wrap">
          <div>
            <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/50 font-medium">
              Expected Move
            </div>
            <div className="font-semibold text-[14px] text-foreground mt-0.5">
              {pick.expected_move_pct}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/50 font-medium">
              Risk / Reward
            </div>
            <div className="font-semibold text-[14px] text-foreground mt-0.5">
              {pick.risk_reward}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/50 font-medium">
              Position Size
            </div>
            <div className="font-semibold text-[14px] text-foreground mt-0.5">
              {pick.position_size_suggestion}
            </div>
          </div>
        </div>

        {/* Reasoning */}
        <div className="text-[13px] text-foreground/70 mt-4 leading-relaxed">
          {pick.reasoning}
        </div>

        {/* Key signals */}
        {pick.key_signals?.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-3">
            {pick.key_signals.map((s, i) => (
              <Badge key={i} variant="blue">
                {s}
              </Badge>
            ))}
          </div>
        )}

        {/* Entry / Exit / Risks — expandable */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 mt-3 text-[12px] font-semibold text-foreground/40 hover:text-foreground/70 transition-colors cursor-pointer"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? "Hide details" : "Entry / Exit / Risks"}
        </button>

        {expanded && (
          <div className="mt-3 pt-3 border-t border-border space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/50 font-medium mb-1">
                  Entry Strategy
                </div>
                <div className="text-[13px] text-foreground/80 leading-relaxed">
                  {pick.entry_strategy}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/50 font-medium mb-1">
                  Exit Strategy
                </div>
                <div className="text-[13px] text-foreground/80 leading-relaxed">
                  {pick.exit_strategy}
                </div>
              </div>
            </div>

            {pick.risk_factors?.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/50 font-medium mb-1.5">
                  Risk Factors
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {pick.risk_factors.map((r, i) => (
                    <Badge key={i} variant="amber">
                      {r}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </GradientCard>
    </StaggerItem>
  );
}


function ModeSelector({
  mode,
  onChange,
}: {
  mode: ScanMode;
  onChange: (m: ScanMode) => void;
}) {
  const options: { value: ScanMode; label: string }[] = [
    { value: "both", label: "Both" },
    { value: "stocks", label: "Stocks" },
    { value: "crypto", label: "Crypto" },
  ];

  return (
    <div className="relative rounded-[1rem] border-[0.75px] border-border p-[3px]">
      <GlowingEffect
        spread={40}
        glow
        disabled={false}
        proximity={64}
        inactiveZone={0.01}
        borderWidth={2}
      />
      <div className="relative flex rounded-[0.625rem] border-[0.75px] border-border bg-background overflow-hidden">
        {options.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={`px-4 py-2 text-[13px] font-semibold transition-colors cursor-pointer ${
              mode === opt.value
                ? "bg-foreground/10 text-foreground"
                : "text-foreground/50 hover:text-foreground/80"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Scorecard ────────────────────────────────────────────────

function Scorecard({ data, onCheckOutcomes }: { data: ScorecardData; onCheckOutcomes: () => void }) {
  const [showHistory, setShowHistory] = useState(false);
  const wrColor = data.win_rate >= 55 ? "#00ccb1" : data.win_rate >= 45 ? "#fbbf24" : "#fb7185";
  const retColor = data.avg_return >= 0 ? "#00ccb1" : "#fb7185";

  return (
    <GradientCard>
      <div className="space-y-4">
        {/* Top stats row */}
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-6">
            {/* Win rate */}
            <div className="text-center">
              <div className="text-[28px] font-black tabular-nums leading-none" style={{ color: wrColor }}>
                {data.win_rate}%
              </div>
              <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/50 font-medium mt-1">
                Win Rate
              </div>
            </div>

            {/* Avg return */}
            <div className="text-center">
              <div className="text-[28px] font-black tabular-nums leading-none" style={{ color: retColor }}>
                {data.avg_return >= 0 ? "+" : ""}{data.avg_return}%
              </div>
              <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/50 font-medium mt-1">
                Avg Return
              </div>
            </div>

            {/* Record */}
            <div className="text-center">
              <div className="text-[22px] font-bold tabular-nums leading-none text-foreground">
                {data.winners}W-{data.losers}L
              </div>
              <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/50 font-medium mt-1">
                {data.total_picks} picks
              </div>
            </div>

            {/* Streak */}
            {data.streak && data.streak !== "0" && (
              <div className="text-center">
                <div className="flex items-center gap-1">
                  <Flame className="h-4 w-4" style={{ color: data.streak.includes("W") ? "#00ccb1" : "#fb7185" }} />
                  <span className="text-[18px] font-bold tabular-nums" style={{ color: data.streak.includes("W") ? "#00ccb1" : "#fb7185" }}>
                    {data.streak}
                  </span>
                </div>
                <div className="text-[10px] uppercase tracking-[0.8px] text-foreground/50 font-medium mt-1">
                  Streak
                </div>
              </div>
            )}
          </div>

          <button
            onClick={onCheckOutcomes}
            className="text-[11px] font-semibold text-foreground/40 hover:text-foreground/70 transition-colors cursor-pointer flex items-center gap-1"
          >
            <Clock className="h-3.5 w-3.5" />
            Check outcomes
          </button>
        </div>

        {/* Confidence calibration */}
        {Object.keys(data.calibration).length > 0 && (
          <div className="flex gap-4 flex-wrap">
            {Object.entries(data.calibration).map(([bucket, stats]) => (
              <div key={bucket} className="flex items-center gap-2">
                <span className="text-[11px] text-foreground/40 font-medium">{bucket}:</span>
                <span
                  className="text-[12px] font-bold tabular-nums"
                  style={{ color: stats.win_rate >= 55 ? "#00ccb1" : stats.win_rate >= 45 ? "#fbbf24" : "#fb7185" }}
                >
                  {stats.win_rate}% ({stats.wins}/{stats.total})
                </span>
              </div>
            ))}
          </div>
        )}

        {/* By type */}
        <div className="flex gap-4 flex-wrap">
          {data.by_type.stocks.total > 0 && (
            <div className="flex items-center gap-1.5">
              <BarChart3 className="h-3.5 w-3.5 text-foreground/40" />
              <span className="text-[12px] text-foreground/60">
                Stocks: {data.by_type.stocks.wins}/{data.by_type.stocks.total}
                {data.by_type.stocks.avg_return !== undefined && (
                  <span style={{ color: data.by_type.stocks.avg_return >= 0 ? "#00ccb1" : "#fb7185" }}>
                    {" "}({data.by_type.stocks.avg_return >= 0 ? "+" : ""}{data.by_type.stocks.avg_return}%)
                  </span>
                )}
              </span>
            </div>
          )}
          {data.by_type.crypto.total > 0 && (
            <div className="flex items-center gap-1.5">
              <Bitcoin className="h-3.5 w-3.5 text-foreground/40" />
              <span className="text-[12px] text-foreground/60">
                Crypto: {data.by_type.crypto.wins}/{data.by_type.crypto.total}
                {data.by_type.crypto.avg_return !== undefined && (
                  <span style={{ color: data.by_type.crypto.avg_return >= 0 ? "#00ccb1" : "#fb7185" }}>
                    {" "}({data.by_type.crypto.avg_return >= 0 ? "+" : ""}{data.by_type.crypto.avg_return}%)
                  </span>
                )}
              </span>
            </div>
          )}
        </div>

        {/* Recent history toggle */}
        <button
          onClick={() => setShowHistory(!showHistory)}
          className="flex items-center gap-1 text-[12px] font-semibold text-foreground/40 hover:text-foreground/70 transition-colors cursor-pointer"
        >
          {showHistory ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {showHistory ? "Hide history" : `Recent picks (${data.recent_picks.length})`}
          {data.pending_picks.length > 0 && (
            <Badge variant="amber">{data.pending_picks.length} pending</Badge>
          )}
        </button>

        {showHistory && (
          <div className="space-y-1.5">
            {data.pending_picks.map((p, idx) => (
              <div
                key={`${p.symbol}-${p.scan_date}-${idx}`}
                className="flex items-center justify-between px-3 py-2 rounded-lg border border-border bg-background/50"
              >
                <div className="flex items-center gap-2">
                  <Clock className="h-3.5 w-3.5 text-amber-400" />
                  <span className="text-[13px] font-semibold text-foreground/70">{p.symbol}</span>
                  <Badge variant="amber">Pending</Badge>
                </div>
                <div className="flex items-center gap-3 text-[12px] text-foreground/50">
                  <span>${p.entry_price}</span>
                  <span>Conf: {p.confidence}</span>
                  <span>{p.scan_date}</span>
                </div>
              </div>
            ))}
            {data.recent_picks.map((p, idx) => (
              <div
                key={`${p.symbol}-${p.scan_date}-${idx}`}
                className="flex items-center justify-between px-3 py-2 rounded-lg border border-border bg-background/50"
              >
                <div className="flex items-center gap-2">
                  {p.won ? (
                    <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
                  ) : (
                    <TrendingDown className="h-3.5 w-3.5 text-rose-400" />
                  )}
                  <span className="text-[13px] font-semibold text-foreground/70">{p.symbol}</span>
                  <span
                    className="text-[12px] font-bold tabular-nums"
                    style={{ color: p.won ? "#00ccb1" : "#fb7185" }}
                  >
                    {p.return_pct >= 0 ? "+" : ""}{p.return_pct}%
                  </span>
                </div>
                <div className="flex items-center gap-3 text-[12px] text-foreground/50">
                  <span>${p.entry_price} → ${p.exit_price}</span>
                  <span>Conf: {p.confidence}</span>
                  <span>{p.scan_date}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </GradientCard>
  );
}

// ── Page ─────────────────────────────────────────────────────

export default function OvernightPage() {
  const [mode, setMode] = useState<ScanMode>("both");
  const [scorecard, setScorecard] = useState<ScorecardData | null>(null);

  const scan = useSSEScan<OvernightResult>(
    "overnight",
    "/overnight/stream",
    "/overnight/status",
  );

  const fetchScorecard = useCallback(() => {
    apiGet<ScorecardData>("/overnight/scorecard").then(setScorecard);
  }, []);

  useEffect(() => {
    fetchScorecard();
  }, [fetchScorecard]);

  // Refresh scorecard when scan completes
  useEffect(() => {
    if (scan.status === "done") fetchScorecard();
  }, [scan.status, fetchScorecard]);

  const handleCheckOutcomes = useCallback(() => {
    apiPost<{ scorecard: ScorecardData }>("/overnight/check-outcomes").then((res) => {
      if (res?.scorecard) setScorecard(res.scorecard);
    });
  }, []);

  const result = scan.result;
  const macro = result?.macro_regime;
  const stockBuys = (result?.stock_picks ?? []).filter((p) => p.action === "BUY");
  const cryptoBuys = (result?.crypto_picks ?? []).filter((p) => p.action === "BUY");
  const pct = scan.total > 0 ? Math.round((scan.progress / scan.total) * 100) : 0;

  return (
    <>
      <PageHeader
        title="AI Overnight Scanner"
        subtitle="Pure AI reasoning over pre-filtered data — computed indicators, not raw candles"
        description="Fetches data from 8 APIs, computes RSI/Bollinger/volume in Python, pre-filters for activity, discovers dynamic movers, then sends only interesting tickers to Claude. Cross-asset correlation checks, sector clustering detection, liquidity validation, and performance memory included."
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            {scan.status === "done" && scan.resultTimestamp && (
              <CacheAge timestamp={scan.resultTimestamp} />
            )}
            <ModeSelector mode={mode} onChange={setMode} />
            <GradientButton
              onClick={() =>
                scan.start("/overnight/start-scan", { mode })
              }
              disabled={scan.status === "scanning"}
            >
              {scan.status === "scanning" ? (
                <>
                  <Sun className="h-4 w-4 animate-spin" />
                  Scanning...
                </>
              ) : (
                <>
                  <Moon className="h-4 w-4" />
                  Scan Now
                </>
              )}
            </GradientButton>
          </div>
        }
      />


      {/* Performance scorecard — show if data OR pending picks exist */}
      {scorecard && (scorecard.has_data || (scorecard.pending_picks?.length > 0)) && (
        <SlideUp>
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Trophy className="h-5 w-5 text-foreground/60" />
                <h2 className="text-[16px] font-bold text-foreground">Performance</h2>
                {scorecard.has_data && (
                  <Badge variant={scorecard.win_rate >= 55 ? "green" : scorecard.win_rate >= 45 ? "amber" : "red"}>
                    Last 30 days
                  </Badge>
                )}
                {!scorecard.has_data && scorecard.pending_picks?.length > 0 && (
                  <Badge variant="amber">
                    {scorecard.pending_picks.length} pending
                  </Badge>
                )}
              </div>
              <GradientButton onClick={handleCheckOutcomes}>
                <Clock className="h-4 w-4" />
                Check Outcomes
              </GradientButton>
            </div>
            {scorecard.has_data ? (
              <Scorecard data={scorecard} onCheckOutcomes={handleCheckOutcomes} />
            ) : (
              <GradientCard>
                <div className="space-y-1.5">
                  {scorecard.pending_picks?.map((p, idx) => (
                    <div
                      key={`${p.symbol}-${p.scan_date}-${idx}`}
                      className="flex items-center justify-between px-3 py-2 rounded-lg border border-border bg-background/50"
                    >
                      <div className="flex items-center gap-2">
                        <Clock className="h-3.5 w-3.5 text-amber-400" />
                        <span className="text-[13px] font-semibold text-foreground/70">{p.symbol}</span>
                        <Badge variant="amber">Pending</Badge>
                      </div>
                      <div className="flex items-center gap-3 text-[12px] text-foreground/50">
                        <span>${p.entry_price}</span>
                        <span>Conf: {p.confidence}</span>
                        <span>{p.scan_date}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </GradientCard>
            )}
          </div>
        </SlideUp>
      )}

      {/* Scanning state */}
      {scan.status === "scanning" && (
        <SlideUp>
          <GradientCard>
            <PulseLoader
              size="lg"
              label={scan.step || "Starting scan..."}
              sublabel="Fetching data from 8 APIs and sending to Claude for analysis. This takes 1-3 minutes."
              progress={pct}
            />
          </GradientCard>
        </SlideUp>
      )}

      {/* Error state */}
      {scan.status === "error" && scan.error && (
        <SlideUp>
          <GradientCard>
            <div className="flex items-center gap-3 text-rose-400">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              <div>
                <div className="text-[14px] font-semibold">Scan Failed</div>
                <p className="text-[13px] text-foreground/60 mt-1">
                  {scan.error}
                </p>
              </div>
            </div>
          </GradientCard>
        </SlideUp>
      )}

      {/* Results */}
      {scan.status === "done" && result && (
        <div className="space-y-6">
          {/* Market intel banner — macro + correlation + weekend in one block */}
          <SlideUp>
            <GradientCard>
              <div className="space-y-3">
                {/* Macro bias header */}
                {macro && (
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="flex items-center gap-2">
                      <span
                        className="w-2.5 h-2.5 rounded-full shrink-0"
                        style={{ background: BIAS_CONFIG[macro.bias]?.color ?? "#fbbf24" }}
                      />
                      <span className="text-[13px] font-bold text-foreground">
                        Macro: {macro.bias.charAt(0).toUpperCase() + macro.bias.slice(1)}
                      </span>
                    </div>
                    {macro.key_factors?.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {macro.key_factors.map((f, i) => (
                          <Badge key={i} variant="purple">{f}</Badge>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Market summary */}
                {(result.market_summary || macro?.summary) && (
                  <p className="text-[13px] text-foreground/70 leading-relaxed">
                    {result.market_summary || macro?.summary}
                  </p>
                )}

                {/* Correlation warning inline */}
                {result.correlation_warning && (
                  <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/15">
                    <AlertTriangle className="h-3.5 w-3.5 text-amber-400 mt-0.5 shrink-0" />
                    <p className="text-[12px] text-amber-400/90 leading-relaxed">
                      {result.correlation_warning}
                    </p>
                  </div>
                )}

                {/* Weekend note inline */}
                {result.market_closed_note && (
                  <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-blue-500/5 border border-blue-500/15">
                    <Moon className="h-3.5 w-3.5 text-blue-400 mt-0.5 shrink-0" />
                    <p className="text-[12px] text-blue-400/90 leading-relaxed">
                      {result.market_closed_note}
                    </p>
                  </div>
                )}
              </div>
            </GradientCard>
          </SlideUp>

          {/* Stock picks */}
          {(mode === "both" || mode === "stocks") && (
            <SlideUp delay={0.15}>
              <div className="mb-3 flex items-center gap-2">
                <BarChart3 className="h-5 w-5 text-foreground/60" />
                <h2 className="text-[16px] font-bold text-foreground">
                  Stock Overnight Picks
                </h2>
                <Badge variant={stockBuys.length > 0 ? "green" : "gray"}>
                  {stockBuys.length} trade{stockBuys.length !== 1 ? "s" : ""}
                </Badge>
              </div>
              {stockBuys.length === 0 ? (
                <GradientCard>
                  <div className="py-2">
                    <div className="text-[14px] font-semibold text-foreground/70 mb-2">
                      No stock trades tonight
                    </div>
                    <p className="text-[13px] text-foreground/50 leading-relaxed">
                      {result.no_stock_reason ||
                        "No setups passed the confidence threshold."}
                    </p>
                  </div>
                </GradientCard>
              ) : (
                <StaggerGroup className="flex flex-col gap-4">
                  {stockBuys.map((pick, i) => (
                    <PickCard key={pick.symbol} pick={pick} type="stock" rank={i + 1} />
                  ))}
                </StaggerGroup>
              )}
            </SlideUp>
          )}

          {/* Crypto picks */}
          {(mode === "both" || mode === "crypto") && (
            <SlideUp delay={0.25}>
              <div className="mb-3 flex items-center gap-2">
                <Bitcoin className="h-5 w-5 text-foreground/60" />
                <h2 className="text-[16px] font-bold text-foreground">
                  Crypto 24h Picks
                </h2>
                <Badge variant={cryptoBuys.length > 0 ? "green" : "gray"}>
                  {cryptoBuys.length} trade{cryptoBuys.length !== 1 ? "s" : ""}
                </Badge>
              </div>
              {cryptoBuys.length === 0 ? (
                <GradientCard>
                  <div className="py-2">
                    <div className="text-[14px] font-semibold text-foreground/70 mb-2">
                      No crypto trades today
                    </div>
                    <p className="text-[13px] text-foreground/50 leading-relaxed">
                      {result.no_crypto_reason ||
                        "No setups passed the confidence threshold."}
                    </p>
                  </div>
                </GradientCard>
              ) : (
                <StaggerGroup className="grid gap-4 grid-cols-1 lg:grid-cols-2">
                  {cryptoBuys.map((pick, i) => (
                    <PickCard key={pick.symbol} pick={pick} type="crypto" rank={i + 1} />
                  ))}
                </StaggerGroup>
              )}
            </SlideUp>
          )}

          {/* Skipped picks (collapsed) */}
          <SkippedPicks
            stockSkips={(result.stock_picks ?? []).filter((p) => p.action === "SKIP")}
            cryptoSkips={(result.crypto_picks ?? []).filter((p) => p.action === "SKIP")}
            mode={mode}
          />
        </div>
      )}
    </>
  );
}

function SkippedPicks({
  stockSkips,
  cryptoSkips,
  mode,
}: {
  stockSkips: OvernightPick[];
  cryptoSkips: OvernightPick[];
  mode: ScanMode;
}) {
  const [open, setOpen] = useState(false);
  const total =
    (mode !== "crypto" ? stockSkips.length : 0) +
    (mode !== "stocks" ? cryptoSkips.length : 0);

  if (total === 0) return null;

  return (
    <SlideUp delay={0.4}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-foreground/40 hover:text-foreground/60 transition-colors text-[13px] font-medium cursor-pointer"
      >
        {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        {total} ticker{total !== 1 ? "s" : ""} analyzed but skipped
      </button>
      {open && (
        <div className="mt-3 space-y-2">
          {mode !== "crypto" &&
            stockSkips.map((p) => (
              <div
                key={p.symbol}
                className="flex items-center justify-between px-4 py-2.5 rounded-xl border border-border bg-background/50"
              >
                <div className="flex items-center gap-2">
                  <span className="text-[14px] font-semibold text-foreground/60">
                    {p.symbol}
                  </span>
                  <Badge variant="gray">SKIP</Badge>
                </div>
                <span className="text-[12px] text-foreground/40 max-w-[60%] truncate text-right">
                  {p.reasoning}
                </span>
              </div>
            ))}
          {mode !== "stocks" &&
            cryptoSkips.map((p) => (
              <div
                key={p.symbol}
                className="flex items-center justify-between px-4 py-2.5 rounded-xl border border-border bg-background/50"
              >
                <div className="flex items-center gap-2">
                  <span className="text-[14px] font-semibold text-foreground/60">
                    {p.symbol}
                  </span>
                  <Badge variant="gray">SKIP</Badge>
                </div>
                <span className="text-[12px] text-foreground/40 max-w-[60%] truncate text-right">
                  {p.reasoning}
                </span>
              </div>
            ))}
        </div>
      )}
    </SlideUp>
  );
}
