"use client";

import { motion } from "framer-motion";
import { SlideUp } from "@/components/motion-primitives";
import { useState, useCallback } from "react";
import { PulseLoader, PulseInline } from "@/components/pulse-loader";
import { PageHeader } from "@/components/page-header";
import { AICard } from "@/components/ai-card";
import { MetricCard } from "@/components/metric-card";
import { CacheAge } from "@/components/cache-age";
import { GradientCard, GradientButton } from "@/components/gradient-card";
import { GlowingEffect } from "@/components/ui/glowing-effect";
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

  const rankColors = ["#34d399", "#60a5fa", "#fbbf24"];

  return (
    <>
      <PageHeader
        title="AI Investment Research"
        subtitle="Your personalized long-term investment plan"
        description="Tell us how much you want to invest, and AI will find the 3 best stocks to buy right now for medium to long-term growth (1-6 months). You'll get exact share counts, plain-English explanations of why each stock is a good bet, when to buy, and what to watch out for. This is different from Swing Picks — these are patient investments, not quick trades."
      />

      {/* Capital Input */}
      <div className="relative rounded-[1.25rem] border-[0.75px] border-border p-2 mb-6 md:rounded-[1.5rem] md:p-3">
        <GlowingEffect
          spread={40}
          glow
          disabled={false}
          proximity={64}
          inactiveZone={0.01}
          borderWidth={3}
        />
        <div className="relative rounded-xl border-[0.75px] border-border bg-background px-8 py-6 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
          <h3 className="text-[16px] font-semibold text-foreground mb-1">
            How much are you investing?
          </h3>
          <p className="text-[13px] text-foreground/80 mb-5">
            Enter your total capital and we&apos;ll find the best 3 stocks to buy right now, with
            exact share counts, entry prices, and a plain-English thesis for each.
          </p>

          {/* Preset buttons */}
          <div className="flex flex-wrap gap-2 mb-4">
            {PRESET_AMOUNTS.map((amt) => (
              <button
                key={amt}
                onClick={() => setCapital(amt)}
                className={`cursor-pointer px-4 py-2 rounded-xl text-sm font-medium transition-colors ${
                  capital === amt
                    ? "bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] text-white shadow-sm"
                    : "bg-muted border-[0.75px] border-border text-foreground/80 hover:bg-background hover:border-foreground/20"
                }`}
              >
                ${amt.toLocaleString()}
              </button>
            ))}
          </div>

          {/* Custom input */}
          <div className="flex flex-col sm:flex-row gap-3 items-center">
            <button
              type="button"
              onClick={() => setCapital((c) => Math.max(100, c - 100))}
              style={{ border: "none", outline: "none", boxShadow: "none" }}
              className="bg-transparent cursor-pointer px-3 py-2.5 text-foreground/40 hover:text-foreground hover:bg-muted/50 transition-colors text-lg font-medium leading-none rounded-lg"
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
              className="w-28 py-2.5 bg-transparent text-foreground text-lg font-semibold text-center appearance-none"
            />
            <button
              type="button"
              onClick={() => setCapital((c) => c + 100)}
              style={{ border: "none", outline: "none", boxShadow: "none" }}
              className="bg-transparent cursor-pointer px-3 py-2.5 text-foreground/40 hover:text-foreground hover:bg-muted/50 transition-colors text-lg font-medium leading-none rounded-lg"
            >
              +
            </button>
            {scan.status === "done" && scan.resultTimestamp && !scan.isLoading && (
              <CacheAge timestamp={scan.resultTimestamp} />
            )}
            <GradientButton
              onClick={startResearch}
              disabled={scan.isLoading || capital < 100}
            >
              {scan.isLoading && <PulseInline />}
              {scan.isLoading
                ? "Researching..."
                : aiResult
                  ? "Refresh Picks"
                  : "Find My Top 3 Picks"}
            </GradientButton>
          </div>
        </div>
      </div>

      {/* Scanning / AI Progress */}
      {scan.status === "scanning" && (
        <GradientCard className="mb-6" innerClassName="px-8 py-10 text-center">
          <PulseLoader
            size="lg"
            label={`Finding your top picks... ${pct}%`}
            progress={pct}
            sublabel={scan.step || "Analyzing sectors, signals, and fundamentals to find the best opportunities."}
          />
        </GradientCard>
      )}

      {/* Error */}
      {scan.status === "error" && (
        <GradientCard className="mb-6" innerClassName="px-8 py-6 text-center">
          <div className="text-[15px] font-semibold text-rose-400 mb-1">
            Research failed
          </div>
          <p className="text-[13px] text-foreground/60">{scan.error}</p>
        </GradientCard>
      )}

      {/* Results */}
      {scan.status === "done" && aiResult && (
        <>
          {/* Market Context */}
          {aiResult.market_context && (
            <AICard title="Market Context" accentColor="#6c5ce7">
              <p className="text-foreground">{aiResult.market_context}</p>
            </AICard>
          )}

          {/* Portfolio Strategy */}
          {aiResult.portfolio_note && (
            <AICard title="Portfolio Strategy" accentColor="#60a5fa">
              <p className="text-foreground">{aiResult.portfolio_note}</p>
            </AICard>
          )}

          {/* Individual Picks */}
          <div className="relative rounded-[1.25rem] border-[0.75px] border-border p-2 mt-6 md:rounded-[1.5rem] md:p-3">
            <GlowingEffect
              spread={40}
              glow
              disabled={false}
              proximity={64}
              inactiveZone={0.01}
              borderWidth={3}
            />
            <div className="relative rounded-xl border-[0.75px] border-border bg-background px-6 py-5 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
              <h3 className="text-[18px] font-bold text-foreground mb-6">
                Your Top 3 Investment Picks
              </h3>

              {aiResult.picks.map((p, idx) => {
                const color = rankColors[(p.rank - 1) % 3];
                const currentPrice = priceMap[p.ticker];
                return (
                  <motion.div
                    key={p.ticker}
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.4,
                      delay: (p.rank - 1) * 0.08,
                      ease: [0.25, 0.46, 0.45, 0.94],
                    }}
                    className={idx < aiResult.picks.length - 1 ? "mb-6 pb-6 border-b border-border" : ""}
                  >
                    {/* Header */}
                    <div className="flex items-center gap-3 mb-4">
                      <span
                        className="text-xl font-extrabold"
                        style={{ color }}
                      >
                        #{p.rank}
                      </span>
                      <div>
                        <span className="text-[17px] font-bold text-foreground">
                          {p.ticker}
                        </span>
                        {p.company_name && (
                          <span className="text-[13px] text-foreground/60 ml-2">
                            {p.company_name}
                          </span>
                        )}
                        {currentPrice != null && currentPrice > 0 && (
                          <span className="text-[14px] font-semibold text-foreground ml-3">
                            {formatDollar(currentPrice)}
                          </span>
                        )}
                      </div>
                      <span className="ml-auto text-[13px] font-semibold text-blue-400 bg-blue-500/5 px-2.5 py-1 rounded-lg">
                        {p.allocation_pct}% of capital
                      </span>
                    </div>

                    {/* Metrics */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
                      <MetricCard label="Invest" value={formatDollar(p.invest_amount)} />
                      <MetricCard label="Shares" value={`${p.shares}`} />
                      <MetricCard label="If Target Hit" value={p.target_dollars} deltaColor="green" />
                      <MetricCard label="If Stop Hit" value={p.stop_dollars} deltaColor="red" />
                    </div>

                    {/* Thesis */}
                    <div className="space-y-3">
                      <div className="px-4 py-3 bg-emerald-500/5 rounded-xl border border-emerald-500/10">
                        <div className="text-[11px] font-semibold text-emerald-400 uppercase tracking-wide mb-1">
                          Investment Thesis
                        </div>
                        <p className="text-[13px] text-foreground leading-relaxed">{p.thesis}</p>
                      </div>

                      <div className="flex gap-3">
                        <div className="flex-1 px-4 py-3 bg-blue-500/5 rounded-xl border border-blue-500/10">
                          <div className="text-[11px] font-semibold text-blue-400 uppercase tracking-wide mb-1">
                            Entry Strategy
                          </div>
                          <p className="text-[13px] text-foreground">{p.entry_strategy}</p>
                        </div>
                        <div className="w-40 px-4 py-3 bg-muted rounded-xl border-[0.75px] border-border">
                          <div className="text-[11px] font-semibold text-foreground/60 uppercase tracking-wide mb-1">
                            Hold Period
                          </div>
                          <p className="text-[13px] text-foreground font-semibold">{p.hold_period}</p>
                        </div>
                      </div>

                      <div className="px-4 py-3 bg-rose-500/5 rounded-xl border border-rose-500/10">
                        <div className="text-[11px] font-semibold text-rose-400 uppercase tracking-wide mb-1">
                          Risk Warning
                        </div>
                        <p className="text-[13px] text-foreground leading-relaxed">{p.risk}</p>
                      </div>
                    </div>
                  </motion.div>
                );
              })}

              <div className="mt-6 pt-5 border-t border-border">
                <p className="text-[12px] text-foreground/60 leading-relaxed">
                  <strong>Disclaimer:</strong> This is AI-generated research for educational purposes only.
                  It is not financial advice. Past performance does not guarantee future results. Always do
                  your own research and consider consulting a licensed financial advisor before making
                  investment decisions. Never invest money you cannot afford to lose.
                </p>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Done but no AI result (picks found but AI failed) */}
      {scan.status === "done" && !aiResult && picks.length > 0 && (
        <GradientCard innerClassName="px-8 py-10 text-center">
          <p className="text-foreground/80 text-sm">
            Found {picks.length} stocks but AI research could not be generated.
            Try refreshing.
          </p>
        </GradientCard>
      )}

      {/* No picks found */}
      {scan.status === "done" && picks.length === 0 && (
        <GradientCard innerClassName="px-8 py-10 text-center">
          <p className="text-foreground/80 text-sm">
            No strong investment opportunities found right now.
            The market conditions may not favor new positions. Try again later.
          </p>
        </GradientCard>
      )}

      {/* Idle state */}
      {scan.status === "idle" && (
        <SlideUp>
          <GradientCard innerClassName="px-8 py-10">
            <h3 className="text-lg font-semibold text-foreground mb-2">
              How It Works
            </h3>
            <div className="space-y-3 text-[14px] text-foreground/80 leading-relaxed">
              <div className="flex gap-3">
                <span className="bg-gradient-to-r from-[#00ccb1] to-[#7b61ff] bg-clip-text text-transparent font-bold text-lg">1.</span>
                <p>Enter your capital — how much you want to invest total.</p>
              </div>
              <div className="flex gap-3">
                <span className="bg-gradient-to-r from-[#00ccb1] to-[#7b61ff] bg-clip-text text-transparent font-bold text-lg">2.</span>
                <p>We scan sectors, fundamentals, and strategy signals to find the best 3 stocks right now.</p>
              </div>
              <div className="flex gap-3">
                <span className="bg-gradient-to-r from-[#00ccb1] to-[#7b61ff] bg-clip-text text-transparent font-bold text-lg">3.</span>
                <p>AI generates a personalized investment plan — how much to put in each stock, when to buy, and what to watch for.</p>
              </div>
            </div>
            <div className="mt-5 p-4 bg-blue-500/5 rounded-xl border border-blue-500/10">
              <p className="text-[13px] text-foreground">
                <strong>Different from Swing Picks:</strong> These are <strong>medium to long-term holds (1-6 months)</strong> targeting
                steady 30%+ returns. Swing Picks are short-term trades (3-10 days) with higher risk and volatility.
              </p>
            </div>
          </GradientCard>
        </SlideUp>
      )}
    </>
  );
}
