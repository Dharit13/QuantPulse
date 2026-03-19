const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// Deduplication: if multiple components request the same GET path at the same
// time (e.g. 3 components all calling /regime/current on mount), share the
// same in-flight promise instead of making 3 separate HTTP requests.
const _inflight: Record<string, Promise<unknown>> = {};
const _getCache: Record<string, { data: unknown; ts: number }> = {};
const GET_CACHE_TTL_MS = 30_000; // 30s

async function request<T>(
  path: string,
  options?: RequestInit & { params?: Record<string, string | number> }
): Promise<T | null> {
  try {
    let url = `${API_BASE}${path}`;
    if (options?.params) {
      const search = new URLSearchParams();
      for (const [k, v] of Object.entries(options.params)) {
        search.set(k, String(v));
      }
      url += `?${search.toString()}`;
    }

    const { params: _, ...fetchOptions } = options || {};
    const res = await fetch(url, {
      ...fetchOptions,
      headers: {
        "Content-Type": "application/json",
        ...fetchOptions?.headers,
      },
    });
    if (!res.ok) {
      console.warn(`[API] ${options?.method ?? "GET"} ${path} → ${res.status}`);
      return null;
    }
    return res.json();
  } catch (err) {
    console.warn(`[API] ${options?.method ?? "GET"} ${path} failed:`, err);
    return null;
  }
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number>
): Promise<T | null> {
  const cacheKey = params
    ? `${path}?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()}`
    : path;

  const cached = _getCache[cacheKey];
  if (cached && Date.now() - cached.ts < GET_CACHE_TTL_MS) {
    return cached.data as T;
  }

  if (_inflight[cacheKey]) {
    return _inflight[cacheKey] as Promise<T | null>;
  }

  const promise = request<T>(path, { params }).then((data) => {
    delete _inflight[cacheKey];
    if (data !== null) {
      _getCache[cacheKey] = { data, ts: Date.now() };
    }
    return data;
  });

  _inflight[cacheKey] = promise;
  return promise;
}

export async function apiPost<T>(
  path: string,
  body?: Record<string, unknown>,
  params?: Record<string, string | number>
): Promise<T | null> {
  return request<T>(path, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
    params,
  });
}

export async function checkHealth(): Promise<boolean> {
  try {
    const base = API_BASE.replace(/\/api\/v1$/, "");
    const res = await fetch(`${base}/health`, { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

export function fetcher<T>(path: string): Promise<T | null> {
  return apiGet<T>(path);
}
