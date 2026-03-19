import type { BadgeVariant } from "./types";

export interface EntrySignal {
  ticker: string;
  label: string;
  detail: string;
  simple?: string;
  variant: BadgeVariant;
  isAI?: boolean;
}

/**
 * Smart fallback when AI is unavailable.
 * Uses price/entry gap, RSI, R/R ratio, and upside to target
 * to give actionable entry advice.
 */
export function fallbackEntrySignal(
  ticker: string,
  price: number,
  entry: number,
  stop?: number,
  target?: number,
  rsi?: number,
): EntrySignal {
  if (!price || !entry || entry <= 0) {
    return { ticker, label: "No data", detail: "", variant: "gray" };
  }

  const pctFromEntry = ((price - entry) / entry) * 100;
  const risk = stop ? Math.abs(entry - stop) : 0;
  const reward = target ? Math.abs(target - entry) : 0;
  const rr = risk > 0 ? reward / risk : 0;
  const upsideToTarget = target && price > 0 ? ((target - price) / price) * 100 : 0;

  const oversold = rsi !== undefined && rsi < 35;
  const veryOversold = rsi !== undefined && rsi < 25;
  const overbought = rsi !== undefined && rsi > 70;
  const rsiNote = rsi !== undefined ? ` (RSI ${rsi.toFixed(0)})` : "";

  // Price below entry — always good
  if (pctFromEntry <= -3) {
    return {
      ticker,
      label: "Below entry — buy",
      detail: `${Math.abs(pctFromEntry).toFixed(1)}% below suggested entry${veryOversold ? ", deeply oversold" : oversold ? ", oversold" : ""} — ideal buy zone`,
      variant: "green",
    };
  }

  if (pctFromEntry <= 0) {
    return {
      ticker,
      label: "At entry — good time",
      detail: `Right at suggested entry${oversold ? ", oversold" + rsiNote + " — strong setup" : " — enter now"}`,
      variant: "green",
    };
  }

  // Slightly above entry (0-3%)
  if (pctFromEntry <= 3) {
    if (oversold) {
      return {
        ticker,
        label: "Good price — enter",
        detail: `Only ${pctFromEntry.toFixed(1)}% above entry and oversold${rsiNote} — still a strong entry`,
        variant: "green",
      };
    }
    return {
      ticker,
      label: "Good price",
      detail: `${pctFromEntry.toFixed(1)}% above entry — close enough, you can enter`,
      variant: "green",
    };
  }

  // Moderately above entry (3-6%)
  if (pctFromEntry <= 6) {
    if (oversold) {
      return {
        ticker,
        label: "Still OK — oversold",
        detail: `${pctFromEntry.toFixed(1)}% above entry but RSI ${rsi!.toFixed(0)} is oversold — the dip supports entry`,
        variant: "green",
      };
    }
    if (upsideToTarget > 25 && rr > 2.5) {
      return {
        ticker,
        label: "Acceptable — upside intact",
        detail: `${pctFromEntry.toFixed(1)}% above entry, but ${upsideToTarget.toFixed(0)}% upside remains with ${rr.toFixed(1)}:1 R/R`,
        variant: "amber",
      };
    }
    return {
      ticker,
      label: "Wait for a dip",
      detail: `${pctFromEntry.toFixed(1)}% above entry — a pullback would give better risk/reward${rsiNote}`,
      variant: "amber",
    };
  }

  // Significantly above entry (6-12%)
  if (pctFromEntry <= 12) {
    if (overbought) {
      return {
        ticker,
        label: "Don't enter — overbought",
        detail: `${pctFromEntry.toFixed(1)}% above entry and RSI ${rsi!.toFixed(0)} is overbought — high risk of pullback`,
        variant: "red",
      };
    }
    if (upsideToTarget > 20 && rr > 3) {
      return {
        ticker,
        label: "Extended — smaller size only",
        detail: `${pctFromEntry.toFixed(1)}% above entry, R/R ${rr.toFixed(1)}:1 still OK — half-size position at most`,
        variant: "amber",
      };
    }
    return {
      ticker,
      label: "Don't enter now",
      detail: `${pctFromEntry.toFixed(1)}% above entry — wait for a meaningful pullback toward $${entry.toFixed(0)}`,
      variant: "red",
    };
  }

  // Way above entry (12%+)
  return {
    ticker,
    label: "Late — missed the move",
    detail: `${pctFromEntry.toFixed(1)}% above entry — risk/reward is no longer favorable, wait for next setup${overbought ? ", overbought" + rsiNote : ""}`,
    variant: "red",
  };
}
