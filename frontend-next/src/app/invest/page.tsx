"use client";

import { useState, useCallback } from "react";
import { PulseLoader, PulseInline } from "@/components/pulse-loader";
import { PageHeader } from "@/components/page-header";
import { AICard } from "@/components/ai-card";
import { MetricCard } from "@/components/metric-card";
import { CacheAge } from "@/components/cache-age";
import { useSSEScan } from "@/hooks/use-sse-scan";
import { formatDollar } from "@/lib/utils";

interface InvestPick {
  ticker: string;
  company_name?: string;
  rank: number;
  allocation_pct: number;
  shares: number;
  invest_amount: number;
  entry_strategy: string;
  stop_dollars: string;
  target_dollars: string;
  hold_period: string;
  thesis: string;
  risk: string;
}

interface InvestResult {
  picks: InvestPick[];
  portfolio_note: string;
  market_context?: string;
}

interface PortfolioResult {
  picks: Array<{
    ticker: string;
    name?: string;
    sector?: string;
    price: number;
    score: number;
    why: string;
    entry?: number;
    stop_loss?: number;
    target?: number;
    rsi?: number;
  }>;
  capital: number;
  regime: string;
}

const PRESET_AMOUNTS = [500, 1000, 2500, 5000, 10000, 25000];

export default function InvestPage() {
  const scan = useSSEScan<PortfolioResult>(
    "portfolio",
    "/portfolio/quick-allocate/stream",
    "/portfolio/quick-allocate/status",
  );
  const [capital, setCapital] = useState(1000);

  const picks = scan.result?.picks ?? [];
  const aiResult = scan.aiSummary as InvestResult | null;
  const pct = scan.total > 0 ? Math.round((scan.progress / scan.total) * 100) : 0;

  const priceMap: Record<string, number> = {};
  for (const p of picks) {
    priceMap[p.ticker] = p.price;
  }

  const startResearch = useCallback(() => {
    scan.start("/portfolio/quick-allocate/start", { capital });
  }, [capital, scan]);

  const rankColors = ["#539616", "#3b7dd8", "#c6a339"];

  return (
    <>
      <PageHeader
        title="AI Investment Research"
        subtitle="Your personalized long-term investment plan"
        description="Tell us how much you want to invest, and AI will find the 3 best stocks to buy right now for long-term growth (6-12 months). You'll get exact share counts, plain-English explanations of why each stock is a good bet, when to buy, and what to watch out for. This is different from Swing Picks — these are patient investments, not quick trades."
      />

      {/* Capital Input */}
      <div
        className="bg-card border border-border rounded-2xl px-8 py-6 mb-6"
        style={{ boxShadow: "var(--shadow-card)" }}
      >
        <h3 className="text-[16px] font-semibold text-text-primary mb-1">
          How much are you investing?
        </h3>
        <p className="text-[13px] text-text-secondary mb-5">
          Enter your total capital and we&apos;ll find the best 3 stocks to buy right now, with
          exact share counts, entry prices, and a plain-English thesis for each.
        </p>

        {/* Preset buttons */}
        <div className="flex flex-wrap gap-2 mb-4">
          {PRESET_AMOUNTS.map((amt) => (
            <button
              key={amt}
              onClick={() => setCapital(amt)}
              className={`px-4 py-2 rounded-xl text-sm font-medium transition-colors ${
                capital === amt
                  ? "bg-accent text-white shadow-sm"
                  : "bg-card-alt border border-border text-text-body hover:bg-card hover:border-accent/30"
              }`}
            >
              ${amt.toLocaleString()}
            </button>
          ))}
        </div>

        {/* Custom input */}
        <div className="flex gap-3 items-stretch">
          <div className="flex items-center bg-card border border-border rounded-xl overflow-hidden focus-within:border-accent focus-within:ring-1 focus-within:ring-accent/30 transition-colors">
            <button
              type="button"
              onClick={() => setCapital((c) => Math.max(100, c - 100))}
              className="px-3 py-2.5 text-text-muted hover:text-text-primary hover:bg-card-alt transition-colors text-lg font-medium leading-none"
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
                className="w-28 py-2.5 bg-transparent text-text-primary font-mono text-sm text-center focus:outline-none appearance-none"
              />
            </div>
            <button
              type="button"
              onClick={() => setCapital((c) => c + 100)}
              className="px-3 py-2.5 text-text-muted hover:text-text-primary hover:bg-card-alt transition-colors text-lg font-medium leading-none"
            >
              +
            </button>
          </div>
          <div className="flex items-center gap-2">
            {scan.status === "done" && scan.resultTimestamp && !scan.isLoading && (
              <CacheAge timestamp={scan.resultTimestamp} />
            )}
            <button
              onClick={startResearch}
              disabled={scan.isLoading || capital < 100}
              className="flex items-center gap-2 px-6 py-2.5 bg-accent text-white rounded-xl text-sm font-semibold hover:bg-accent-light transition-colors shadow-sm disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {scan.isLoading && <PulseInline />}
              {scan.isLoading
                ? "Researching..."
                : aiResult
                  ? "Refresh Picks"
                  : "Find My Top 3 Picks"}
            </button>
          </div>
        </div>
      </div>

      {/* Scanning / AI Progress */}
      {scan.status === "scanning" && (
        <div
          className="bg-card border border-border rounded-2xl px-8 py-10 text-center mb-6"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <PulseLoader
            size="lg"
            label={`Finding your top picks... ${pct}%`}
            progress={pct}
            sublabel={scan.step || "Analyzing sectors, signals, and fundamentals to find the best opportunities."}
          />
        </div>
      )}

      {/* Error */}
      {scan.status === "error" && (
        <div className="bg-qp-red-bg border border-qp-red/15 rounded-2xl px-8 py-6 text-center mb-6">
          <div className="text-[15px] font-semibold text-qp-red mb-1">
            Research failed
          </div>
          <p className="text-[13px] text-text-muted">{scan.error}</p>
        </div>
      )}

      {/* Results */}
      {scan.status === "done" && aiResult && (
        <>
          {/* Market Context */}
          {aiResult.market_context && (
            <AICard title="Market Context" accentColor="#6c5ce7">
              <p className="text-text-primary">{aiResult.market_context}</p>
            </AICard>
          )}

          {/* Portfolio Strategy */}
          {aiResult.portfolio_note && (
            <AICard title="Portfolio Strategy" accentColor="#3b7dd8">
              <p className="text-text-primary">{aiResult.portfolio_note}</p>
            </AICard>
          )}

          {/* Individual Picks */}
          <h3 className="text-[18px] font-bold text-text-primary mb-4 mt-6">
            Your Top 3 Investment Picks
          </h3>

          {aiResult.picks.map((p) => {
            const color = rankColors[(p.rank - 1) % 3];
            const currentPrice = priceMap[p.ticker];
            return (
              <div
                key={p.ticker}
                className="bg-card border border-border rounded-2xl px-6 py-5 mb-4"
                style={{
                  boxShadow: "var(--shadow-card)",
                  borderLeftWidth: 4,
                  borderLeftColor: color,
                }}
              >
                {/* Header */}
                <div className="flex items-center gap-3 mb-4">
                  <span
                    className="text-xl font-extrabold font-mono"
                    style={{ color }}
                  >
                    #{p.rank}
                  </span>
                  <div>
                    <span className="text-[17px] font-bold text-text-primary">
                      {p.ticker}
                    </span>
                    {p.company_name && (
                      <span className="text-[13px] text-text-muted ml-2">
                        {p.company_name}
                      </span>
                    )}
                    {currentPrice != null && currentPrice > 0 && (
                      <span className="text-[14px] font-mono font-semibold text-text-primary ml-3">
                        {formatDollar(currentPrice)}
                      </span>
                    )}
                  </div>
                  <span className="ml-auto text-[13px] font-semibold text-accent bg-accent-bg px-2.5 py-1 rounded-lg">
                    {p.allocation_pct}% of capital
                  </span>
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-4 gap-4 mb-4">
                  <MetricCard label="Invest" value={formatDollar(p.invest_amount)} />
                  <MetricCard label="Shares" value={`${p.shares}`} />
                  <MetricCard label="If Target Hit" value={p.target_dollars} deltaColor="green" />
                  <MetricCard label="If Stop Hit" value={p.stop_dollars} deltaColor="red" />
                </div>

                {/* Thesis */}
                <div className="space-y-3">
                  <div className="px-4 py-3 bg-qp-green-bg rounded-xl border border-qp-green/15">
                    <div className="text-[11px] font-semibold text-qp-green uppercase tracking-wide mb-1">
                      Investment Thesis
                    </div>
                    <p className="text-[13px] text-text-primary leading-relaxed">{p.thesis}</p>
                  </div>

                  <div className="flex gap-3">
                    <div className="flex-1 px-4 py-3 bg-accent-bg rounded-xl border border-accent/15">
                      <div className="text-[11px] font-semibold text-accent uppercase tracking-wide mb-1">
                        Entry Strategy
                      </div>
                      <p className="text-[13px] text-text-primary">{p.entry_strategy}</p>
                    </div>
                    <div className="w-40 px-4 py-3 bg-card-alt rounded-xl border border-border">
                      <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wide mb-1">
                        Hold Period
                      </div>
                      <p className="text-[13px] text-text-primary font-semibold">{p.hold_period}</p>
                    </div>
                  </div>

                  <div className="px-4 py-3 bg-qp-red-bg rounded-xl border border-qp-red/15">
                    <div className="text-[11px] font-semibold text-qp-red uppercase tracking-wide mb-1">
                      Risk Warning
                    </div>
                    <p className="text-[13px] text-text-primary leading-relaxed">{p.risk}</p>
                  </div>
                </div>
              </div>
            );
          })}

          {/* Disclaimer */}
          <div className="mt-6 px-6 py-4 bg-card-alt rounded-2xl border border-border">
            <p className="text-[12px] text-text-muted leading-relaxed">
              <strong>Disclaimer:</strong> This is AI-generated research for educational purposes only.
              It is not financial advice. Past performance does not guarantee future results. Always do
              your own research and consider consulting a licensed financial advisor before making
              investment decisions. Never invest money you cannot afford to lose.
            </p>
          </div>
        </>
      )}

      {/* Done but no AI result (picks found but AI failed) */}
      {scan.status === "done" && !aiResult && picks.length > 0 && (
        <div
          className="bg-card border border-border rounded-2xl px-8 py-10 text-center"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <p className="text-text-secondary text-sm">
            Found {picks.length} stocks but AI research could not be generated.
            Try refreshing.
          </p>
        </div>
      )}

      {/* No picks found */}
      {scan.status === "done" && picks.length === 0 && (
        <div
          className="bg-card border border-border rounded-2xl px-8 py-10 text-center"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <p className="text-text-secondary text-sm">
            No strong investment opportunities found right now.
            The market conditions may not favor new positions. Try again later.
          </p>
        </div>
      )}

      {/* Idle state */}
      {scan.status === "idle" && (
        <div
          className="bg-card border border-border rounded-2xl px-8 py-10"
          style={{
            boxShadow: "var(--shadow-card)",
            borderLeft: "4px solid #3b7dd8",
          }}
        >
          <h3 className="text-lg font-semibold text-text-primary mb-2">
            How It Works
          </h3>
          <div className="space-y-3 text-[14px] text-text-body leading-relaxed">
            <div className="flex gap-3">
              <span className="text-accent font-bold text-lg">1.</span>
              <p>Enter your capital — how much you want to invest total.</p>
            </div>
            <div className="flex gap-3">
              <span className="text-accent font-bold text-lg">2.</span>
              <p>We scan sectors, fundamentals, and strategy signals to find the best 3 stocks right now.</p>
            </div>
            <div className="flex gap-3">
              <span className="text-accent font-bold text-lg">3.</span>
              <p>AI generates a personalized investment plan — how much to put in each stock, when to buy, and what to watch for.</p>
            </div>
          </div>
          <div className="mt-5 p-4 bg-accent-bg rounded-xl border border-accent/15">
            <p className="text-[13px] text-text-primary">
              <strong>Different from Swing Picks:</strong> These are <strong>long-term holds (6-12 months)</strong> targeting
              steady 30%+ returns. Swing Picks are short-term trades (3-10 days) with higher risk and volatility.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
