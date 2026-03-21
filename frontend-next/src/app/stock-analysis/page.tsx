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
import { PriceChart } from "@/components/price-chart";
import { formatDollar, formatCompact, formatPercent } from "@/lib/utils";
import { GradientCard, GradientButton } from "@/components/gradient-card";
import { GlowingEffect } from "@/components/ui/glowing-effect";
import { SlideUp, StaggerGroup, StaggerItem } from "@/components/motion-primitives";
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
    <div className="relative rounded-[1.25rem] border-[0.75px] border-border p-2 mb-3 md:rounded-[1.5rem] md:p-3">
      <GlowingEffect
        spread={40}
        glow
        disabled={false}
        proximity={64}
        inactiveZone={0.01}
        borderWidth={3}
      />
      <div className="relative rounded-xl border-[0.75px] border-border bg-background overflow-hidden shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
        <button
          onClick={() => setOpen(!open)}
          className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-muted transition-colors active:scale-[0.99] cursor-pointer"
        >
          <span className="text-[15px] font-semibold text-foreground">
            {title}
          </span>
          <ChevronDown
            className={`h-4 w-4 text-foreground/60 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          />
        </button>
        {open && <div className="px-6 pb-5 pt-0">{children}</div>}
      </div>
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
      <div className="relative rounded-[1.25rem] border-[0.75px] border-border p-2 mb-8 md:rounded-[1.5rem] md:p-3">
        <GlowingEffect
          spread={40}
          glow
          disabled={false}
          proximity={64}
          inactiveZone={0.01}
          borderWidth={3}
        />
      <div className="relative flex flex-col sm:flex-row gap-3 items-center rounded-xl border-[0.75px] border-border bg-background px-5 py-4 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && analyze()}
          placeholder="Ticker or company name"
          style={{ border: "none", outline: "none", boxShadow: "none" }}
          className="flex-1 max-w-sm px-4 py-2.5 bg-transparent text-foreground text-lg font-semibold placeholder:text-foreground/30"
        />
        <button
          type="button"
          onClick={() => setCapital((c) => Math.max(50, c - 50))}
          style={{ border: "none", outline: "none", boxShadow: "none" }}
          className="bg-transparent px-3 py-2.5 text-foreground/40 hover:text-foreground hover:bg-muted/50 transition-colors active:scale-[0.95] cursor-pointer text-lg font-medium leading-none"
        >
          −
        </button>
        <span style={{ border: "none", outline: "none" }} className="text-foreground/40 text-sm">$</span>
        <input
          type="text"
          inputMode="numeric"
          value={capital.toLocaleString()}
          onChange={(e) => {
            const num = Number(e.target.value.replace(/,/g, ""));
            if (!isNaN(num) && num >= 0) setCapital(num);
          }}
          style={{ border: "none", outline: "none", boxShadow: "none" }}
          className="w-24 py-2.5 bg-transparent text-foreground text-lg font-semibold text-center appearance-none"
        />
        <button
          type="button"
          onClick={() => setCapital((c) => c + 50)}
          style={{ border: "none", outline: "none", boxShadow: "none" }}
          className="bg-transparent px-3 py-2.5 text-foreground/40 hover:text-foreground hover:bg-muted/50 transition-colors active:scale-[0.95] cursor-pointer text-lg font-medium leading-none"
        >
          +
        </button>
        <GradientButton onClick={analyze} disabled={loading}>
          {loading && <PulseInline />}
          {loading ? "Analyzing..." : "Analyze"}
        </GradientButton>
      </div>
      </div>

      {/* Loading */}
      {loading && (
        <GradientCard innerClassName="px-8 py-12 text-center">
          <PulseLoader
            size="lg"
            label={`Analyzing ${ticker}... ${pct}%`}
            progress={pct}
            sublabel={step || "Running technicals, fundamentals, signals, and AI analysis."}
          />
        </GradientCard>
      )}

      {/* Error */}
      {error && (
        <GradientCard innerClassName="px-8 py-6 text-center">
          <p className="text-rose-400 font-semibold">{error}</p>
        </GradientCard>
      )}

      {/* Results */}
      {data && tech && take && (
        <>
          {/* Zone 1: Stock Header */}
          <SlideUp>
            <div className="relative rounded-[1.25rem] border-[0.75px] border-border p-2 mb-6 md:rounded-[1.5rem] md:p-3">
              <GlowingEffect
                spread={40}
                glow
                disabled={false}
                proximity={64}
                inactiveZone={0.01}
                borderWidth={3}
              />
              <div className="relative flex items-baseline gap-4 flex-wrap rounded-xl border-[0.75px] border-border bg-background px-6 py-5 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
                <span className="text-[32px] font-extrabold text-foreground">
                  {data.ticker}
                </span>
                <span className="text-2xl font-semibold text-foreground">
                  {formatDollar(price)}
                </span>
                <span
                  className="text-base font-semibold"
                  style={{ color: ret1d >= 0 ? "#34d399" : "#fb7185" }}
                >
                  {formatPercent(ret1d)}
                </span>
                {data.resolved_from && (
                  <span className="text-[13px] text-foreground/60">
                    (searched: {data.resolved_from})
                  </span>
                )}
              </div>
            </div>
          </SlideUp>

          <StaggerGroup className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <StaggerItem className="h-full">
              <MetricCard label="Sector" value={data.sector} />
            </StaggerItem>
            <StaggerItem className="h-full">
              <MetricCard
                label="Market Regime"
                value={data.regime.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
              />
            </StaggerItem>
            <StaggerItem className="h-full">
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
            </StaggerItem>
          </StaggerGroup>

          {/* Price Chart (when backend provides OHLC data) */}
          {data.price_history && data.price_history.length > 0 && (
            <SlideUp delay={0.05} className="mb-6">
              <PriceChart
                data={data.price_history.map((d) => ({
                  time: d.date as `${number}-${number}-${number}`,
                  open: d.open,
                  high: d.high,
                  low: d.low,
                  close: d.close,
                }))}
                volumeData={data.price_history.map((d) => ({
                  time: d.date as `${number}-${number}-${number}`,
                  value: d.volume,
                  color: d.close >= d.open ? "rgba(38,166,154,0.4)" : "rgba(239,83,80,0.4)",
                }))}
                height={320}
              />
            </SlideUp>
          )}

          {/* Zone 2: Verdict */}
          <SlideUp delay={0.1}>
          <VerdictCard
            title={bias.toUpperCase()}
            verdictType={biasToVerdict(bias)}
            score={score}
          >
            {take.summary && (
              <p className="text-[15px] text-foreground leading-relaxed">
                {take.summary}
              </p>
            )}
            {take.return_outlook && (
              <div className="mt-4 px-4 py-3 bg-blue-500/5 rounded-xl border border-blue-500/10">
                <div className="text-[12px] font-semibold text-blue-400 uppercase tracking-wide mb-1">
                  30% Return Outlook
                </div>
                <div className="text-[14px] text-foreground">
                  {take.return_outlook}
                </div>
              </div>
            )}
            {take.notes.length > 0 && (
              <div className="mt-4">
                <div className="text-[12px] font-semibold text-blue-400 uppercase tracking-wide mb-2">
                  Key Observations
                </div>
                <ul className="list-disc pl-5 text-[14px] text-foreground/80 leading-relaxed space-y-1">
                  {take.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </div>
            )}
          </VerdictCard>
          </SlideUp>

          {/* Zone 3: Trade Plan */}
          {showPlan && plan && (
            <SlideUp delay={0.15}>
            <div className="mt-6">
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
                  Your Trade Plan
                </h3>
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
                    <span className="text-[13px] text-foreground/60">
                      {plan.entry_note}
                    </span>
                  )}
                </div>

                <div className="flex gap-6 flex-wrap">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-foreground/60 font-medium">
                      Entry
                    </div>
                    <div className="font-semibold text-foreground">
                      {formatDollar(plan.entry_price)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-foreground/60 font-medium">
                      Stop Loss
                    </div>
                    <div className="font-semibold text-rose-400">
                      {formatDollar(plan.stop_loss)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-foreground/60 font-medium">
                      Target
                    </div>
                    <div className="font-semibold text-emerald-400">
                      {formatDollar(plan.target_2 > plan.target_1 ? plan.target_2 : plan.target_1)}
                      {" "}
                      <span className="text-foreground/60 text-[12px]">
                        (+{plan.target_2 > plan.target_1 ? plan.target_2_pct : plan.target_1_pct}%)
                      </span>
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-foreground/60 font-medium">
                      R/R Ratio
                    </div>
                    <div className="font-semibold text-foreground">
                      {plan.risk_reward.toFixed(1)}:1
                    </div>
                  </div>
                </div>

                {plan.sizing.shares > 0 && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-5 pt-4 border-t border-border">
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
                  <div className="mt-4 px-4 py-3 bg-amber-500/5 rounded-xl border border-amber-500/15">
                    <span className="text-[13px] text-foreground">
                      <strong className="text-amber-400">Budget too small:</strong>{" "}
                      {plan.sizing.note}
                    </span>
                  </div>
                )}

                {at && atUpside > 0 && (
                  <div
                    className="mt-4 px-4 py-3 bg-emerald-500/5 rounded-xl border border-emerald-500/15"
                  >
                    <span className="text-[13px] text-foreground">
                      <strong>Analyst Target:</strong> {formatDollar(at)}{" "}
                      <span className="text-emerald-400 font-semibold">
                        (+{atUpside.toFixed(0)}%)
                      </span>
                      {atUpside >= 30
                        ? " — enough for your 30% goal"
                        : " — below 30% target, may need longer hold"}
                    </span>
                  </div>
                )}

                {(plan.hold_period || plan.time_to_50pct) && (
                  <div className="text-[12px] text-foreground/60 mt-3">
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
            </div>
            </SlideUp>
          )}

          {/* Caution warning — driven by AI bias, not hardcoded score */}
          {plan && (plan.action === "AVOID" || plan.action === "HOLD OFF — NO EDGE") && take.summary && (
            <AICard
              title={
                bias.includes("bearish") ? "Not a Great Time to Buy"
                : bias === "neutral" ? "No Clear Edge Right Now"
                : "Timing Could Be Better"
              }
              accentColor={bias.includes("bearish") ? "#fb7185" : "#fbbf24"}
              className="mt-6"
            >
              <p className="text-foreground">{take.summary}</p>
            </AICard>
          )}

          {/* DCF Valuation */}
          {dcf && (
            <div className="mt-6">
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
                  Valuation
                </h3>
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
                    <div className="text-[11px] uppercase tracking-wider text-foreground/60 font-medium mb-1">
                      Fair Value
                    </div>
                    <div className="text-2xl font-bold text-foreground">
                      {formatDollar(dcf.intrinsic_value)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-foreground/60 font-medium mb-1">
                      Current Price
                    </div>
                    <div className="text-2xl font-bold text-foreground/60">
                      {formatDollar(dcf.current_price)}
                    </div>
                  </div>
                  {dcf.margin_of_safety > 0 && (
                    <div>
                      <div className="text-[11px] uppercase tracking-wider text-foreground/60 font-medium mb-1">
                        Margin of Safety
                      </div>
                      <div className="text-2xl font-bold text-emerald-400">
                        {dcf.margin_of_safety.toFixed(0)}%
                      </div>
                    </div>
                  )}
                </div>

                {dcf.reasoning && (
                  <p className="text-[14px] text-foreground/80 leading-relaxed mt-4 pt-4 border-t border-border">
                    {dcf.reasoning}
                  </p>
                )}

                {dcf.assumptions && (
                  <details className="mt-4 pt-3 border-t border-border">
                    <summary className="text-[12px] text-foreground/60 cursor-pointer hover:text-foreground/80">
                      View assumptions
                    </summary>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-3">
                      <div>
                        <div className="text-[10px] text-foreground/60 uppercase tracking-wide">
                          Free Cash Flow
                        </div>
                        <div className="text-[13px] text-foreground">
                          {formatCompact(dcf.assumptions.fcf_latest)}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-foreground/60 uppercase tracking-wide">
                          Growth Rate
                        </div>
                        <div className="text-[13px] text-foreground">
                          {(dcf.assumptions.growth_rate * 100).toFixed(1)}%
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-foreground/60 uppercase tracking-wide">
                          Discount Rate
                        </div>
                        <div className="text-[13px] text-foreground">
                          {(dcf.assumptions.discount_rate * 100).toFixed(1)}%
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-foreground/60 uppercase tracking-wide">
                          Terminal Growth
                        </div>
                        <div className="text-[13px] text-foreground">
                          {(dcf.assumptions.terminal_growth * 100).toFixed(1)}%
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-foreground/60 uppercase tracking-wide">
                          Projection
                        </div>
                        <div className="text-[13px] text-foreground">
                          {dcf.assumptions.projection_years} years
                        </div>
                      </div>
                      {dcf.assumptions.net_cash != null && (
                        <div>
                          <div className="text-[10px] text-foreground/60 uppercase tracking-wide">
                            Net Cash
                          </div>
                          <div className={`text-[13px] ${dcf.assumptions.net_cash >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                            {formatCompact(dcf.assumptions.net_cash)}
                          </div>
                        </div>
                      )}
                    </div>
                  </details>
                )}
                </div>
              </div>
            </div>
          )}

          {/* Sentiment */}
          {sentiment && sentiment.article_count > 0 && (
            <div className="mt-6">
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
                  News Sentiment
                </h3>
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
                  <span className="text-[13px] text-foreground/60">
                    {sentiment.article_count} articles analyzed
                  </span>
                </div>

                <div className="flex gap-8 items-end mb-4">
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-foreground/60 font-medium mb-1">
                      Sentiment Score
                    </div>
                    <div className="text-2xl font-bold text-foreground">
                      {sentiment.composite_score.toFixed(0)}/100
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-foreground/60 font-medium mb-1">
                      Positive
                    </div>
                    <div className="text-lg font-semibold text-emerald-400">
                      {(sentiment.pct_positive * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-foreground/60 font-medium mb-1">
                      Negative
                    </div>
                    <div className="text-lg font-semibold text-rose-400">
                      {(sentiment.pct_negative * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-foreground/60 font-medium mb-1">
                      Neutral
                    </div>
                    <div className="text-lg font-semibold text-foreground/60">
                      {(sentiment.pct_neutral * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>

                {(sentiment.strongest_positive || sentiment.strongest_negative) && (
                  <div className="space-y-2 pt-3 border-t border-border">
                    {sentiment.strongest_positive && (
                      <div className="text-[13px] text-foreground/80">
                        <span className="font-semibold text-emerald-400">Most positive:</span>{" "}
                        {sentiment.strongest_positive}
                      </div>
                    )}
                    {sentiment.strongest_negative && (
                      <div className="text-[13px] text-foreground/80">
                        <span className="font-semibold text-rose-400">Most negative:</span>{" "}
                        {sentiment.strongest_negative}
                      </div>
                    )}
                  </div>
                )}
                </div>
              </div>
            </div>
          )}

          {/* Already Own It */}
          {take.already_own_it && (
            <div className="mt-6">
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
                    title={`Already Own This Stock? — ${own.action}`}
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
                      <div className="px-4 py-3 bg-blue-500/5 rounded-xl border border-blue-500/10 mb-3">
                        <div className="text-[11px] font-semibold text-blue-400 uppercase tracking-wide mb-1">
                          In Plain English
                        </div>
                        <p className="text-[14px] text-foreground leading-relaxed">
                          {own.simple}
                        </p>
                      </div>
                    )}
                    <details className="group">
                      <summary className="text-[12px] text-foreground/60 cursor-pointer hover:text-foreground/80 mb-2">
                        Technical details
                      </summary>
                      <p className="text-[13px] text-foreground/80 leading-relaxed">
                        {own.reasoning}
                      </p>
                    </details>
                    <div className="flex gap-8 mt-4">
                      {own.hold_days > 0 && (
                        <div className="text-center">
                          <div className="text-[11px] text-foreground/60 uppercase tracking-wide">
                            Min Hold
                          </div>
                          <div className="font-bold text-lg text-foreground">
                            {own.hold_days} days
                          </div>
                        </div>
                      )}
                      {own.stop_price > 0 && (
                        <div className="text-center">
                          <div className="text-[11px] text-foreground/60 uppercase tracking-wide">
                            Exit If Below
                          </div>
                          <div className="font-bold text-lg text-rose-400">
                            {formatDollar(own.stop_price)}
                          </div>
                        </div>
                      )}
                      {own.target_price > 0 && (
                        <div className="text-center">
                          <div className="text-[11px] text-foreground/60 uppercase tracking-wide">
                            Target
                          </div>
                          <div className="font-bold text-lg text-emerald-400">
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
          <SlideUp delay={0.2}>
          <div className="mt-8 space-y-0">
            {/* Fundamentals */}
            {fund && (
              <Expandable title="Fundamentals" defaultOpen={score >= 60}>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
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
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
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
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
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

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
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
                          color: "#fb7185",
                        },
                        {
                          label: "Target",
                          value: formatDollar(sig.target),
                          color: "#34d399",
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
                <div className="h-48 bg-transparent">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={perfData} barCategoryGap="30%" style={{ background: 'transparent' }}>
                      <defs>
                        <linearGradient id="barGreen" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#10b981" stopOpacity={1} />
                          <stop offset="100%" stopColor="#10b981" stopOpacity={0.4} />
                        </linearGradient>
                        <linearGradient id="barRed" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#f43f5e" stopOpacity={1} />
                          <stop offset="100%" stopColor="#f43f5e" stopOpacity={0.4} />
                        </linearGradient>
                      </defs>
                      <XAxis
                        dataKey="period"
                        tick={{ fill: "var(--qp-text-muted)", fontSize: 13, fontWeight: 500 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis hide />
                      <Tooltip
                        cursor={{ fill: 'var(--qp-border)', opacity: 0.3 }}
                        contentStyle={{
                          background: "var(--qp-card)",
                          backdropFilter: "blur(16px)",
                          border: "1px solid var(--qp-border)",
                          color: "var(--qp-foreground)",
                          borderRadius: 12,
                          fontSize: 13,
                          fontFamily: "var(--font-sans)",
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
                            fill={d.value >= 0 ? "url(#barGreen)" : "url(#barRed)"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Expandable>
            )}
          </div>
          </SlideUp>
        </>
      )}
    </>
  );
}
