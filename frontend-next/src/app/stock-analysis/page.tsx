"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { PulseLoader, PulseInline } from "@/components/pulse-loader";
import { PageHeader } from "@/components/page-header";
import { MetricCard } from "@/components/metric-card";
import { VerdictCard } from "@/components/verdict-card";
import { AICard } from "@/components/ai-card";
import { TradeCard } from "@/components/trade-card";
import { Badge } from "@/components/badge";
import { useAnalysis } from "@/context/analysis-context";
import { formatDollar, formatCompact, formatPercent } from "@/lib/utils";
import type { BadgeVariant } from "@/lib/types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

type VerdictType = "buy" | "sell" | "avoid" | "wait" | "hold" | "conflict";

function biasToVerdict(bias: string): VerdictType {
  const map: Record<string, VerdictType> = {
    bullish: "buy",
    "lean bullish": "buy",
    "cautiously bullish": "wait",
    neutral: "hold",
    "lean bearish": "avoid",
    bearish: "sell",
  };
  return map[bias] ?? "hold";
}

function Expandable({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div
      className="bg-card border border-border rounded-2xl mb-3 overflow-hidden"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-card-alt transition-colors active:scale-[0.99] cursor-pointer"
      >
        <span className="text-[15px] font-semibold text-text-primary">
          {title}
        </span>
        <ChevronDown
          className={`h-4 w-4 text-text-muted transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="px-6 pb-5 pt-0">{children}</div>}
    </div>
  );
}

export default function StockAnalysisPage() {
  const {
    ticker,
    capital,
    data,
    loading,
    progress,
    total,
    step,
    error,
    setTicker,
    setCapital,
    analyze,
  } = useAnalysis();

  const pct = total > 0 ? Math.round((progress / total) * 100) : 0;

  const tech = data?.technicals;
  const fund = data?.fundamentals;
  const take = data?.system_take;
  const plan = data?.trade_plan;
  const signals = data?.signals ?? [];
  const price = tech?.current_price ?? 0;
  const ret1d = tech?.return_1d ?? 0;
  const bias = take?.bias ?? "neutral";
  const score = take?.score ?? 50;

  const dcf = data?.dcf_valuation;
  const sentiment = data?.sentiment;

  const showPlan = plan && plan.entry_price > 0;

  const at = fund?.analyst_target;
  const atUpside = at && price > 0 ? ((at - price) / price) * 100 : 0;

  const perfData = tech
    ? [
        { period: "1D", value: tech.return_1d },
        { period: "1W", value: tech.return_5d },
        { period: "1M", value: tech.return_20d },
        { period: "3M", value: tech.return_60d },
      ]
    : [];

  return (
    <>
      <PageHeader
        title="Stock Analysis"
        subtitle="Deep dive on any stock you're interested in"
        description="Type any stock ticker or company name, enter how much you'd invest, and hit Analyze. You'll get a full breakdown — whether to buy or skip, a specific trade plan with entry/exit prices, how many shares to buy, and supporting data like fundamentals and technicals. Great for researching a stock someone told you about."
      />

      {/* Input bar */}
      <div className="flex gap-3 mb-8 items-stretch">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && analyze()}
          placeholder="Ticker or company name"
          className="flex-1 max-w-sm px-4 py-2.5 bg-card border border-border rounded-xl text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-colors"
        />
        <div className="flex items-center bg-card border border-border rounded-xl overflow-hidden focus-within:border-accent focus-within:ring-1 focus-within:ring-accent/30 transition-colors">
          <button
            type="button"
            onClick={() => setCapital((c) => Math.max(50, c - 50))}
            className="px-3 py-2.5 text-text-muted hover:text-text-primary hover:bg-card-alt transition-colors active:scale-[0.95] cursor-pointer text-lg font-medium leading-none"
          >
            −
          </button>
          <div className="flex items-center px-1">
            <span className="text-text-muted text-sm mr-0.5">$</span>
            <input
              type="text"
              inputMode="numeric"
              value={capital.toLocaleString()}
              onChange={(e) => {
                const num = Number(e.target.value.replace(/,/g, ""));
                if (!isNaN(num) && num >= 0) setCapital(num);
              }}
              className="w-20 py-2.5 bg-transparent text-text-primary font-mono text-sm text-center focus:outline-none appearance-none"
            />
          </div>
          <button
            type="button"
            onClick={() => setCapital((c) => c + 50)}
            className="px-3 py-2.5 text-text-muted hover:text-text-primary hover:bg-card-alt transition-colors active:scale-[0.95] cursor-pointer text-lg font-medium leading-none"
          >
            +
          </button>
        </div>
        <button
          onClick={analyze}
          disabled={loading}
          className="flex items-center gap-2 px-6 py-2.5 bg-accent text-white rounded-xl text-sm font-semibold hover:bg-accent-light transition-colors active:scale-[0.98] cursor-pointer shadow-sm disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {loading && <PulseInline />}
          {loading ? "Analyzing..." : "Analyze"}
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div
          className="bg-card border border-border rounded-2xl px-8 py-12 text-center"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <PulseLoader
            size="lg"
            label={`Analyzing ${ticker}... ${pct}%`}
            progress={pct}
            sublabel={step || "Running technicals, fundamentals, signals, and AI analysis."}
          />
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-qp-red-bg border border-qp-red/15 rounded-2xl px-8 py-6 text-center">
          <p className="text-qp-red font-semibold">{error}</p>
        </div>
      )}

      {/* Results */}
      {data && tech && take && (
        <>
          {/* Zone 1: Stock Header */}
          <div className="flex items-baseline gap-4 flex-wrap mb-2">
            <span className="text-[32px] font-extrabold text-text-primary font-mono">
              {data.ticker}
            </span>
            <span className="text-2xl font-semibold text-text-primary">
              {formatDollar(price)}
            </span>
            <span
              className="text-base font-semibold"
              style={{ color: ret1d >= 0 ? "#2d9d3a" : "#d44040" }}
            >
              {formatPercent(ret1d)}
            </span>
            {data.resolved_from && (
              <span className="text-[13px] text-text-muted">
                (searched: {data.resolved_from})
              </span>
            )}
          </div>

          <div className="grid grid-cols-3 gap-4 mb-6">
            <MetricCard label="Sector" value={data.sector} />
            <MetricCard
              label="Market Regime"
              value={data.regime.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
            />
            <MetricCard
              label="AI Verdict"
              value={bias.replace(/\b\w/g, (c) => c.toUpperCase())}
              delta={`Confidence: ${score}/100`}
              deltaColor={
                bias.includes("bullish") ? "green"
                : bias.includes("bearish") ? "red"
                : "neutral"
              }
            />
          </div>

          {/* Zone 2: Verdict */}
          <VerdictCard
            title={bias.toUpperCase()}
            verdictType={biasToVerdict(bias)}
            score={score}
          >
            {take.summary && (
              <p className="text-[15px] text-text-primary leading-relaxed">
                {take.summary}
              </p>
            )}
            {take.return_outlook && (
              <div className="mt-4 px-4 py-3 bg-accent-bg rounded-xl border border-accent/15">
                <div className="text-[12px] font-semibold text-accent uppercase tracking-wide mb-1">
                  30% Return Outlook
                </div>
                <div className="text-[14px] text-text-primary">
                  {take.return_outlook}
                </div>
              </div>
            )}
            {take.notes.length > 0 && (
              <div className="mt-4">
                <div className="text-[12px] font-semibold text-accent uppercase tracking-wide mb-2">
                  Key Observations
                </div>
                <ul className="list-disc pl-5 text-[14px] text-text-body leading-relaxed space-y-1">
                  {take.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </div>
            )}
          </VerdictCard>

          {/* Zone 3: Trade Plan */}
          {showPlan && plan && (
            <div className="mt-6">
              <h3 className="text-[18px] font-bold text-text-primary mb-3">
                Your Trade Plan
              </h3>

              <div
                className="bg-card border border-border rounded-2xl px-6 py-5"
                style={{ boxShadow: "var(--shadow-card)" }}
              >
                <div className="flex items-center gap-3 mb-4">
                  <Badge
                    variant={
                      plan.action === "BUY"
                        ? "green"
                        : plan.action === "WAIT FOR BETTER ENTRY"
                          ? "amber"
                          : "blue"
                    }
                  >
                    {plan.action === "BUY"
                      ? "BUY NOW"
                      : plan.action === "WAIT FOR BETTER ENTRY"
                        ? "WAIT FOR DIP"
                        : "WATCH"}
                  </Badge>
                  {plan.entry_note && (
                    <span className="text-[13px] text-text-muted">
                      {plan.entry_note}
                    </span>
                  )}
                </div>

                <div className="flex gap-6 flex-wrap">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-text-muted font-medium">
                      Entry
                    </div>
                    <div className="font-mono font-semibold text-text-primary">
                      {formatDollar(plan.entry_price)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-text-muted font-medium">
                      Stop Loss
                    </div>
                    <div className="font-mono font-semibold text-qp-red">
                      {formatDollar(plan.stop_loss)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-text-muted font-medium">
                      Target
                    </div>
                    <div className="font-mono font-semibold text-qp-green">
                      {formatDollar(plan.target_2 > plan.target_1 ? plan.target_2 : plan.target_1)}
                      {" "}
                      <span className="text-text-muted text-[12px]">
                        (+{plan.target_2 > plan.target_1 ? plan.target_2_pct : plan.target_1_pct}%)
                      </span>
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-text-muted font-medium">
                      R/R Ratio
                    </div>
                    <div className="font-mono font-semibold text-text-primary">
                      {plan.risk_reward.toFixed(1)}:1
                    </div>
                  </div>
                </div>

                {plan.sizing.shares > 0 && (
                  <div className="grid grid-cols-4 gap-4 mt-5 pt-4 border-t border-border">
                    <MetricCard
                      label="Buy"
                      value={`${plan.sizing.shares} shares`}
                    />
                    <MetricCard
                      label="Position"
                      value={formatDollar(plan.sizing.position_value)}
                      delta={`${plan.sizing.position_pct.toFixed(0)}% of capital`}
                    />
                    <MetricCard
                      label="Risk"
                      value={formatDollar(plan.sizing.max_loss)}
                      delta="max loss"
                      deltaColor="red"
                    />
                    <MetricCard
                      label="Reward"
                      value={formatDollar(
                        plan.target_2 > plan.target_1 && plan.sizing.gain_at_target_2
                          ? plan.sizing.gain_at_target_2
                          : plan.sizing.gain_at_target_1
                      )}
                      delta="at target"
                      deltaColor="green"
                    />
                  </div>
                )}

                {plan.sizing.shares === 0 && plan.sizing.note && (
                  <div className="mt-4 px-4 py-3 bg-qp-amber-bg rounded-xl border border-qp-amber/15">
                    <span className="text-[13px] text-text-primary">
                      <strong className="text-qp-amber">Budget too small:</strong>{" "}
                      {plan.sizing.note}
                    </span>
                  </div>
                )}

                {at && atUpside > 0 && (
                  <div
                    className="mt-4 px-4 py-3 bg-qp-green-bg rounded-xl border border-qp-green/15"
                  >
                    <span className="text-[13px] text-text-primary">
                      <strong>Analyst Target:</strong> {formatDollar(at)}{" "}
                      <span className="text-qp-green font-semibold">
                        (+{atUpside.toFixed(0)}%)
                      </span>
                      {atUpside >= 30
                        ? " — enough for your 30% goal"
                        : " — below 30% target, may need longer hold"}
                    </span>
                  </div>
                )}

                {(plan.hold_period || plan.time_to_50pct) && (
                  <div className="text-[12px] text-text-muted mt-3">
                    {plan.hold_period && (
                      <span>
                        <strong>Hold period:</strong> {plan.hold_period}
                      </span>
                    )}
                    {plan.time_to_50pct && (
                      <span>
                        {plan.hold_period ? " | " : ""}
                        <strong>Path to 50% return:</strong>{" "}
                        {plan.time_to_50pct}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Caution warning — driven by AI bias, not hardcoded score */}
          {plan && (plan.action === "AVOID" || plan.action === "HOLD OFF — NO EDGE") && take.summary && (
            <AICard
              title={
                bias.includes("bearish") ? "Not a Great Time to Buy"
                : bias === "neutral" ? "No Clear Edge Right Now"
                : "Timing Could Be Better"
              }
              accentColor={bias.includes("bearish") ? "#d44040" : "#c68a1a"}
              className="mt-6"
            >
              <p className="text-text-primary">{take.summary}</p>
            </AICard>
          )}

          {/* DCF Valuation */}
          {dcf && (
            <div className="mt-6">
              <h3 className="text-[18px] font-bold text-text-primary mb-3">
                Valuation
              </h3>
              <div
                className="bg-card border border-border rounded-2xl px-6 py-5"
                style={{
                  boxShadow: "var(--shadow-card)",
                  borderLeftWidth: 4,
                  borderLeftColor:
                    dcf.verdict === "undervalued"
                      ? "#2d9d3a"
                      : dcf.verdict === "overvalued"
                        ? "#d44040"
                        : "#3b7dd8",
                }}
              >
                <div className="flex items-center gap-3 mb-4">
                  <Badge
                    variant={
                      dcf.verdict === "undervalued"
                        ? "green"
                        : dcf.verdict === "overvalued"
                          ? "red"
                          : "blue"
                    }
                  >
                    {dcf.upside_pct > 0 ? `${dcf.upside_pct.toFixed(0)}% Undervalued` : dcf.upside_pct < 0 ? `${Math.abs(dcf.upside_pct).toFixed(0)}% Overvalued` : "Fairly Valued"}
                  </Badge>
                </div>

                <div className="flex gap-8 items-end">
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-text-muted font-medium mb-1">
                      Fair Value
                    </div>
                    <div className="font-mono text-2xl font-bold text-text-primary">
                      {formatDollar(dcf.intrinsic_value)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-text-muted font-medium mb-1">
                      Current Price
                    </div>
                    <div className="font-mono text-2xl font-bold text-text-muted">
                      {formatDollar(dcf.current_price)}
                    </div>
                  </div>
                  {dcf.margin_of_safety > 0 && (
                    <div>
                      <div className="text-[11px] uppercase tracking-wider text-text-muted font-medium mb-1">
                        Margin of Safety
                      </div>
                      <div className="font-mono text-2xl font-bold text-qp-green">
                        {dcf.margin_of_safety.toFixed(0)}%
                      </div>
                    </div>
                  )}
                </div>

                {/* AI Reasoning */}
                {dcf.reasoning && (
                  <p className="text-[14px] text-text-body leading-relaxed mt-4 pt-4 border-t border-border">
                    {dcf.reasoning}
                  </p>
                )}

                {/* Assumptions (collapsed) */}
                {dcf.assumptions && (
                  <details className="mt-4 pt-3 border-t border-border">
                    <summary className="text-[12px] text-text-muted cursor-pointer hover:text-text-secondary">
                      View assumptions
                    </summary>
                    <div className="grid grid-cols-3 gap-3 mt-3">
                      <div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wide">
                          Free Cash Flow
                        </div>
                        <div className="text-[13px] font-mono text-text-primary">
                          {formatCompact(dcf.assumptions.fcf_latest)}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wide">
                          Growth Rate
                        </div>
                        <div className="text-[13px] font-mono text-text-primary">
                          {(dcf.assumptions.growth_rate * 100).toFixed(1)}%
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wide">
                          Discount Rate
                        </div>
                        <div className="text-[13px] font-mono text-text-primary">
                          {(dcf.assumptions.discount_rate * 100).toFixed(1)}%
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wide">
                          Terminal Growth
                        </div>
                        <div className="text-[13px] font-mono text-text-primary">
                          {(dcf.assumptions.terminal_growth * 100).toFixed(1)}%
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wide">
                          Projection
                        </div>
                        <div className="text-[13px] font-mono text-text-primary">
                          {dcf.assumptions.projection_years} years
                        </div>
                      </div>
                      {dcf.assumptions.net_cash != null && (
                        <div>
                          <div className="text-[10px] text-text-muted uppercase tracking-wide">
                            Net Cash
                          </div>
                          <div className={`text-[13px] font-mono ${dcf.assumptions.net_cash >= 0 ? "text-qp-green" : "text-qp-red"}`}>
                            {formatCompact(dcf.assumptions.net_cash)}
                          </div>
                        </div>
                      )}
                    </div>
                  </details>
                )}
              </div>
            </div>
          )}

          {/* Sentiment */}
          {sentiment && sentiment.article_count > 0 && (
            <div className="mt-6">
              <h3 className="text-[18px] font-bold text-text-primary mb-3">
                News Sentiment
              </h3>
              <div
                className="bg-card border border-border rounded-2xl px-6 py-5"
                style={{
                  boxShadow: "var(--shadow-card)",
                  borderLeftWidth: 4,
                  borderLeftColor:
                    sentiment.sentiment_label === "bullish"
                      ? "#2d9d3a"
                      : sentiment.sentiment_label === "bearish"
                        ? "#d44040"
                        : "#3b7dd8",
                }}
              >
                <div className="flex items-center gap-3 mb-4">
                  <Badge
                    variant={
                      sentiment.sentiment_label === "bullish"
                        ? "green"
                        : sentiment.sentiment_label === "bearish"
                          ? "red"
                          : "blue"
                    }
                  >
                    {sentiment.sentiment_label.toUpperCase()}
                  </Badge>
                  <span className="text-[13px] text-text-muted">
                    {sentiment.article_count} articles analyzed
                  </span>
                </div>

                <div className="flex gap-8 items-end mb-4">
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-text-muted font-medium mb-1">
                      Sentiment Score
                    </div>
                    <div className="font-mono text-2xl font-bold text-text-primary">
                      {sentiment.composite_score.toFixed(0)}/100
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-text-muted font-medium mb-1">
                      Positive
                    </div>
                    <div className="font-mono text-lg font-semibold text-qp-green">
                      {(sentiment.pct_positive * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-text-muted font-medium mb-1">
                      Negative
                    </div>
                    <div className="font-mono text-lg font-semibold text-qp-red">
                      {(sentiment.pct_negative * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-text-muted font-medium mb-1">
                      Neutral
                    </div>
                    <div className="font-mono text-lg font-semibold text-text-muted">
                      {(sentiment.pct_neutral * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>

                {(sentiment.strongest_positive || sentiment.strongest_negative) && (
                  <div className="space-y-2 pt-3 border-t border-border">
                    {sentiment.strongest_positive && (
                      <div className="text-[13px] text-text-body">
                        <span className="font-semibold text-qp-green">Most positive:</span>{" "}
                        {sentiment.strongest_positive}
                      </div>
                    )}
                    {sentiment.strongest_negative && (
                      <div className="text-[13px] text-text-body">
                        <span className="font-semibold text-qp-red">Most negative:</span>{" "}
                        {sentiment.strongest_negative}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Already Own It */}
          {take.already_own_it && (
            <div className="mt-6">
              <h3 className="text-[18px] font-bold text-text-primary mb-3">
                Already Own This Stock?
              </h3>
              {(() => {
                const own = take.already_own_it!;
                const ownVerdict: VerdictType =
                  own.action === "BUY MORE"
                    ? "buy"
                    : own.action === "SELL"
                      ? "sell"
                      : own.action.includes("PROFIT")
                        ? "wait"
                        : "hold";
                return (
                  <VerdictCard
                    title={own.action}
                    verdictType={ownVerdict}
                  >
                    <div className="flex items-center gap-2 mb-3">
                      <Badge
                        variant={
                          own.action === "BUY MORE"
                            ? "green"
                            : own.action === "SELL"
                              ? "red"
                              : "blue"
                        }
                      >
                        {own.headline}
                      </Badge>
                    </div>
                    {own.simple && (
                      <div className="px-4 py-3 bg-accent-bg rounded-xl border border-accent/15 mb-3">
                        <div className="text-[11px] font-semibold text-accent uppercase tracking-wide mb-1">
                          In Plain English
                        </div>
                        <p className="text-[14px] text-text-primary leading-relaxed">
                          {own.simple}
                        </p>
                      </div>
                    )}
                    <details className="group">
                      <summary className="text-[12px] text-text-muted cursor-pointer hover:text-text-secondary mb-2">
                        Technical details
                      </summary>
                      <p className="text-[13px] text-text-body leading-relaxed font-mono">
                        {own.reasoning}
                      </p>
                    </details>
                    <div className="flex gap-8 mt-4">
                      {own.hold_days > 0 && (
                        <div className="text-center">
                          <div className="text-[11px] text-text-muted uppercase tracking-wide">
                            Min Hold
                          </div>
                          <div className="font-mono font-bold text-lg text-text-primary">
                            {own.hold_days} days
                          </div>
                        </div>
                      )}
                      {own.stop_price > 0 && (
                        <div className="text-center">
                          <div className="text-[11px] text-text-muted uppercase tracking-wide">
                            Exit If Below
                          </div>
                          <div className="font-mono font-bold text-lg text-qp-red">
                            {formatDollar(own.stop_price)}
                          </div>
                        </div>
                      )}
                      {own.target_price > 0 && (
                        <div className="text-center">
                          <div className="text-[11px] text-text-muted uppercase tracking-wide">
                            Target
                          </div>
                          <div className="font-mono font-bold text-lg text-qp-green">
                            {formatDollar(own.target_price)}
                          </div>
                        </div>
                      )}
                    </div>
                  </VerdictCard>
                );
              })()}
            </div>
          )}

          {/* Zone 4: Supporting Evidence */}
          <div className="mt-8 space-y-0">
            {/* Fundamentals */}
            {fund && (
              <Expandable title="Fundamentals" defaultOpen={score >= 60}>
                <div className="grid grid-cols-3 gap-4">
                  <MetricCard
                    label="Market Cap"
                    value={fund.market_cap ? formatCompact(fund.market_cap) : "N/A"}
                  />
                  <MetricCard
                    label="P/E (TTM)"
                    value={fund.pe_ratio ? fund.pe_ratio.toFixed(1) : "N/A"}
                  />
                  <MetricCard
                    label="Fwd P/E"
                    value={fund.forward_pe ? fund.forward_pe.toFixed(1) : "N/A"}
                  />
                  <MetricCard
                    label="Rev Growth"
                    value={
                      fund.revenue_growth != null
                        ? `${(fund.revenue_growth * 100).toFixed(0)}%`
                        : "N/A"
                    }
                  />
                  <MetricCard
                    label="Profit Margin"
                    value={
                      fund.profit_margin != null
                        ? `${(fund.profit_margin * 100).toFixed(0)}%`
                        : "N/A"
                    }
                  />
                  <MetricCard
                    label="Beta"
                    value={fund.beta ? fund.beta.toFixed(2) : "N/A"}
                  />
                  <MetricCard
                    label="EPS (TTM)"
                    value={fund.eps_trailing ? formatDollar(fund.eps_trailing) : "N/A"}
                  />
                  <MetricCard
                    label="EPS (Fwd)"
                    value={fund.eps_forward ? formatDollar(fund.eps_forward) : "N/A"}
                  />
                  <MetricCard
                    label="Debt/Equity"
                    value={fund.debt_to_equity ? fund.debt_to_equity.toFixed(0) : "N/A"}
                  />
                </div>
              </Expandable>
            )}

            {/* Technicals */}
            <Expandable title="Technicals">
              <div className="grid grid-cols-4 gap-4 mb-4">
                <MetricCard label="Trend" value={tech.trend} />
                <MetricCard label="RSI (14)" value={tech.rsi_14.toFixed(1)} />
                <MetricCard
                  label="ATR (14)"
                  value={formatDollar(tech.atr_14)}
                  delta={`${tech.atr_pct.toFixed(1)}%`}
                />
                <MetricCard
                  label="Vol Ratio"
                  value={`${tech.volume_ratio.toFixed(2)}x`}
                />
              </div>

              {/* MAs */}
              <div className="grid grid-cols-3 gap-4 mb-4">
                {[
                  { label: "SMA 20", val: tech.sma_20 },
                  { label: "SMA 50", val: tech.sma_50 },
                  { label: "SMA 200", val: tech.sma_200 },
                ].map(
                  (ma) =>
                    ma.val && (
                      <MetricCard
                        key={ma.label}
                        label={ma.label}
                        value={formatDollar(ma.val)}
                        delta={formatPercent(
                          ((price / ma.val) - 1) * 100
                        )}
                        deltaColor={price >= ma.val ? "green" : "red"}
                      />
                    )
                )}
              </div>

              <div className="grid grid-cols-4 gap-4">
                <MetricCard
                  label="Support"
                  value={formatDollar(tech.support_20d)}
                />
                <MetricCard
                  label="Resistance"
                  value={formatDollar(tech.resistance_20d)}
                />
                <MetricCard
                  label="52W Low"
                  value={formatDollar(tech.low_52w)}
                />
                <MetricCard
                  label="52W High"
                  value={formatDollar(tech.high_52w)}
                  delta={formatPercent(tech.pct_from_52w_high)}
                  deltaColor="red"
                />
              </div>
            </Expandable>

            {/* Strategy Signals */}
            {signals.length > 0 && (
              <Expandable title="Strategy Signals">
                {signals.map((sig, i) => {
                  const dir = sig.direction.toUpperCase();
                  const dirBadge: BadgeVariant =
                    dir === "LONG" ? "green" : "red";
                  return (
                    <TradeCard
                      key={i}
                      ticker={sig.ticker}
                      badges={[
                        { text: dir, variant: dirBadge },
                        {
                          text: sig.strategy.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
                          variant: "blue",
                        },
                        {
                          text: `Score ${sig.signal_score.toFixed(0)}`,
                          variant: "purple",
                        },
                      ]}
                      stats={[
                        {
                          label: "Entry",
                          value: formatDollar(sig.entry_price),
                        },
                        {
                          label: "Stop",
                          value: formatDollar(sig.stop_loss),
                          color: "#d44040",
                        },
                        {
                          label: "Target",
                          value: formatDollar(sig.target),
                          color: "#2d9d3a",
                        },
                      ]}
                      meta={sig.edge_reason}
                    />
                  );
                })}
              </Expandable>
            )}

            {/* Performance */}
            {perfData.length > 0 && (
              <Expandable title="Recent Performance">
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={perfData} barCategoryGap="30%">
                      <XAxis
                        dataKey="period"
                        tick={{ fill: "var(--color-text-muted)", fontSize: 13 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis hide />
                      <Tooltip
                        contentStyle={{
                          background: "var(--color-card)",
                          border: "1px solid var(--color-border)",
                          color: "var(--color-text-primary)",
                          borderRadius: 12,
                          fontSize: 13,
                          fontFamily: "var(--font-mono)",
                          boxShadow: "var(--shadow-card)",
                        }}
                        formatter={(v) => {
                          const n = Number(v);
                          return [`${n >= 0 ? "+" : ""}${n.toFixed(2)}%`, "Return"];
                        }}
                      />
                      <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                        {perfData.map((d, idx) => (
                          <Cell
                            key={idx}
                            fill={d.value >= 0 ? "#2d9d3a" : "#d44040"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Expandable>
            )}
          </div>
        </>
      )}
    </>
  );
}
