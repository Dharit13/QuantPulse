import { DashboardClient } from "./dashboard-client";

export const dynamic = "force-dynamic";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

async function fetchRegime() {
  try {
    const res = await fetch(`${API_BASE}/regime/current`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = await res.json();
    return body?.data ?? body;
  } catch {
    return null;
  }
}

async function fetchNews() {
  try {
    const res = await fetch(`${API_BASE}/news/market`, { cache: "no-store" });
    if (!res.ok) return null;
    const body = await res.json();
    const payload = body?.data ?? body;
    return payload?.items ?? null;
  } catch {
    return null;
  }
}

export default async function MarketOverviewPage() {
  const [regime, news] = await Promise.all([fetchRegime(), fetchNews()]);

  return (
    <DashboardClient initialRegime={regime} initialNews={news} />
  );
}
