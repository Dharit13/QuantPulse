"use client";

import { useState, useEffect, useCallback } from "react";
import { ExternalLink, Search, RefreshCw, Newspaper, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { GradientCard, GradientButton } from "@/components/gradient-card";
import { GlowingEffect } from "@/components/ui/glowing-effect";
import { AICard } from "@/components/ai-card";
import { SlideUp, StaggerGroup, StaggerItem } from "@/components/motion-primitives";
import { PulseInline } from "@/components/pulse-loader";
import { Badge } from "@/components/badge";
import { apiGet, apiPost } from "@/lib/api";

interface NewsItem {
  title: string;
  source: string;
  url: string;
  published_at: string;
  related_ticker: string;
}

interface NewsResponse {
  items: NewsItem[];
  ticker?: string;
}

interface NewsSummary {
  summary: string;
  sentiment: "bullish" | "bearish" | "neutral" | "mixed";
  key_themes: string[];
  action_note: string;
}

const SENTIMENT_COLORS: Record<string, string> = {
  bullish: "#10b981",
  bearish: "#f43f5e",
  neutral: "#8896a7",
  mixed: "#f59e0b",
};

function timeAgo(dateStr: string): string {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return "";
    const now = new Date();
    const diff = Math.floor((now.getTime() - d.getTime()) / 1000);
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

function NewsCard({ item, index }: { item: NewsItem; index: number }) {
  const ago = timeAgo(item.published_at);

  return (
    <StaggerItem>
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className="group block px-5 py-4 rounded-xl border-[0.75px] border-border bg-background hover:bg-muted/50 transition-all duration-200 hover:border-foreground/10"
      >
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <h4 className="text-[14px] font-medium text-foreground leading-snug group-hover:text-blue-400 transition-colors line-clamp-2">
              {item.title}
            </h4>
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              {item.source && (
                <span className="text-[12px] text-foreground/50 font-medium">
                  {item.source}
                </span>
              )}
              {item.source && ago && (
                <span className="text-foreground/20">·</span>
              )}
              {ago && (
                <span className="text-[12px] text-foreground/40">{ago}</span>
              )}
              {item.related_ticker && (
                <Badge variant="blue">{item.related_ticker}</Badge>
              )}
            </div>
          </div>
          <ExternalLink className="h-4 w-4 text-foreground/20 group-hover:text-foreground/50 transition-colors flex-shrink-0 mt-0.5" />
        </div>
      </a>
    </StaggerItem>
  );
}

export default function NewsPage() {
  const [marketNews, setMarketNews] = useState<NewsItem[]>([]);
  const [tickerNews, setTickerNews] = useState<NewsItem[]>([]);
  const [tickerInput, setTickerInput] = useState("");
  const [searchedTicker, setSearchedTicker] = useState("");
  const [loading, setLoading] = useState(true);
  const [tickerLoading, setTickerLoading] = useState(false);
  const [aiSummary, setAiSummary] = useState<NewsSummary | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [marketAiSummary, setMarketAiSummary] = useState<NewsSummary | null>(null);
  const [marketAiLoading, setMarketAiLoading] = useState(false);

  const fetchMarketNews = useCallback(async () => {
    setSearchedTicker("");
    setTickerNews([]);
    setAiSummary(null);
    setMarketAiSummary(null);
    setLoading(true);
    const resp = await apiGet<NewsResponse>("/news/market");
    const items = resp?.items ?? [];
    setMarketNews(items);
    setLoading(false);

    if (items.length > 0) {
      setMarketAiLoading(true);
      const ai = await apiPost<{ result: NewsSummary }>("/ai/summarize", {
        type: "news_summary",
        data: { ticker: "Market (SPY, QQQ, DIA, IWM, VIX)", items },
      });
      setMarketAiSummary(ai?.result ?? null);
      setMarketAiLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMarketNews();
  }, [fetchMarketNews]);

  const searchTicker = async () => {
    const t = tickerInput.trim().toUpperCase();
    if (!t) return;
    setTickerLoading(true);
    setAiSummary(null);
    setSearchedTicker(t);
    const resp = await apiGet<NewsResponse>(`/news/ticker/${t}`);
    const items = resp?.items ?? [];
    setTickerNews(items);
    setTickerLoading(false);

    if (items.length > 0) {
      setAiLoading(true);
      const ai = await apiPost<{ result: NewsSummary }>("/ai/summarize", {
        type: "news_summary",
        data: { ticker: t, items },
      });
      setAiSummary(ai?.result ?? null);
      setAiLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Market News"
        subtitle="Latest headlines and ticker-specific news"
        description="Stay informed with real-time market headlines from major indices and ETFs. Search any stock ticker to see its latest news. Updated every 15 minutes."
        actions={
          <GradientButton onClick={fetchMarketNews} disabled={loading}>
            {loading ? <PulseInline /> : <RefreshCw className="h-4 w-4" />}
            {loading ? "Loading..." : "Refresh"}
          </GradientButton>
        }
      />

      {/* Ticker search */}
      <div className="relative rounded-[1.25rem] border-[0.75px] border-border p-2 mb-6 md:rounded-[1.5rem] md:p-3">
        <GlowingEffect
          spread={40}
          glow
          disabled={false}
          proximity={64}
          inactiveZone={0.01}
          borderWidth={3}
        />
        <div className="relative flex items-center gap-3 rounded-xl border-[0.75px] border-border bg-background px-5 py-3 shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
          <Search className="h-4 w-4 text-foreground/40 flex-shrink-0" />
          <input
            type="text"
            value={tickerInput}
            onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === "Enter" && searchTicker()}
            placeholder="Search ticker for news (e.g. AAPL, TSLA, NVDA)"
            style={{ border: "none", outline: "none", boxShadow: "none" }}
            className="flex-1 bg-transparent text-foreground text-[15px] font-medium placeholder:text-foreground/30"
          />
          <GradientButton onClick={searchTicker} disabled={tickerLoading || !tickerInput.trim()}>
            {tickerLoading && <PulseInline />}
            {tickerLoading ? "Searching..." : "Search"}
          </GradientButton>
        </div>
      </div>

      {/* Ticker-specific news */}
      {searchedTicker && (
        <SlideUp>
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
              <div className="flex items-center gap-2 mb-4">
                <Newspaper className="h-5 w-5 text-foreground/60" />
                <h3 className="text-[18px] font-bold text-foreground">
                  {searchedTicker} Headlines
                </h3>
              </div>

              {/* AI Brief inside card */}
              {aiLoading && (
                <div className="mb-4 rounded-xl border border-border bg-muted/30 px-5 py-4">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-[#00ccb1]" />
                    <PulseInline />
                    <span className="text-foreground/60 text-sm">Analyzing headlines...</span>
                  </div>
                </div>
              )}
              {aiSummary && !aiLoading && (
                <div className="mb-4 rounded-xl border border-border bg-muted/30 px-5 py-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-[#00ccb1]" />
                    <span className="text-[13px] font-semibold text-foreground">AI Brief</span>
                    <span
                      className="text-[11px] font-semibold uppercase tracking-wider ml-auto"
                      style={{ color: SENTIMENT_COLORS[aiSummary.sentiment] ?? "#8896a7" }}
                    >
                      {aiSummary.sentiment}
                    </span>
                  </div>
                  <p className="text-[14px] leading-[1.7] text-foreground/80">
                    {aiSummary.summary}
                  </p>
                  {aiSummary.key_themes?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {aiSummary.key_themes.map((theme) => (
                        <Badge key={theme} variant="blue">{theme}</Badge>
                      ))}
                    </div>
                  )}
                  {aiSummary.action_note && (
                    <p className="text-[13px] text-foreground/60 italic border-l-2 border-[#00ccb1]/40 pl-3">
                      {aiSummary.action_note}
                    </p>
                  )}
                </div>
              )}

              {tickerLoading ? (
                <div className="py-8 text-center">
                  <PulseInline />
                  <span className="text-foreground/60 text-sm ml-2">Loading news...</span>
                </div>
              ) : tickerNews.length > 0 ? (
                <StaggerGroup className="space-y-2">
                  {tickerNews.slice(0, 10).map((item, i) => (
                    <NewsCard key={`${item.title}-${i}`} item={item} index={i} />
                  ))}
                </StaggerGroup>
              ) : (
                <p className="text-foreground/60 text-sm py-4 text-center">
                  No news found for {searchedTicker}.
                </p>
              )}
            </div>
          </div>
        </SlideUp>
      )}

      {/* Market news -- hidden when a ticker is searched */}
      {!searchedTicker && (
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
            <div className="flex items-center gap-2 mb-4">
              <Newspaper className="h-5 w-5 text-foreground/60" />
              <h3 className="text-[18px] font-bold text-foreground">
                Market Headlines
              </h3>
            </div>

            {/* Market AI Brief inside card */}
            {marketAiLoading && (
              <div className="mb-4 rounded-xl border border-border bg-muted/30 px-5 py-4">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-[#00ccb1]" />
                  <PulseInline />
                  <span className="text-foreground/60 text-sm">Analyzing market headlines...</span>
                </div>
              </div>
            )}
            {marketAiSummary && !marketAiLoading && (
              <div className="mb-4 rounded-xl border border-border bg-muted/30 px-5 py-4 space-y-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-[#00ccb1]" />
                  <span className="text-[13px] font-semibold text-foreground">AI Brief</span>
                  <span
                    className="text-[11px] font-semibold uppercase tracking-wider ml-auto"
                    style={{ color: SENTIMENT_COLORS[marketAiSummary.sentiment] ?? "#8896a7" }}
                  >
                    {marketAiSummary.sentiment}
                  </span>
                </div>
                <p className="text-[14px] leading-[1.7] text-foreground/80">
                  {marketAiSummary.summary}
                </p>
                {marketAiSummary.key_themes?.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {marketAiSummary.key_themes.map((theme) => (
                      <Badge key={theme} variant="blue">{theme}</Badge>
                    ))}
                  </div>
                )}
                {marketAiSummary.action_note && (
                  <p className="text-[13px] text-foreground/60 italic border-l-2 border-[#00ccb1]/40 pl-3">
                    {marketAiSummary.action_note}
                  </p>
                )}
              </div>
            )}

            {loading ? (
              <div className="py-12 text-center">
                <PulseInline />
                <span className="text-foreground/60 text-sm ml-2">Fetching latest headlines...</span>
              </div>
            ) : marketNews.length > 0 ? (
              <StaggerGroup className="space-y-2">
                {marketNews.slice(0, 10).map((item, i) => (
                  <NewsCard key={`${item.title}-${i}`} item={item} index={i} />
                ))}
              </StaggerGroup>
            ) : (
              <GradientCard innerClassName="px-8 py-10 text-center">
                <p className="text-foreground/60 text-sm">
                  No market news available right now. Try refreshing.
                </p>
              </GradientCard>
            )}
          </div>
        </div>
      )}
    </>
  );
}
