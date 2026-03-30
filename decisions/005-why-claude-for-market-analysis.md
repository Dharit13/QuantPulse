# ADR-005: Claude for Market Analysis and Research Enrichment

## Status
Active

## Context
The system needed a reasoning layer for two tasks: (1) enriching quantitative signals with qualitative context (news, management tone, macro narrative), and (2) the overnight scanner — a pure-AI module that reasons about tickers using raw data from 8 APIs.

Options considered: no AI layer (pure quant), fine-tuned open-source model, GPT-4, Claude.

## Decision
Use Anthropic Claude (claude-sonnet and claude-haiku) for all AI reasoning tasks in the system.

## Reasoning

**Instruction following**: Claude's instruction-following fidelity is critical for structured output tasks. The overnight scanner requires Claude to output JSON with specific fields, follow anti-fabrication rules (don't invent insider data), apply a confidence calibration rubric, and check for correlated risk across picks. Claude handles these compound instructions reliably.

**Reasoning quality on financial text**: Financial analysis requires synthesizing across multiple documents, understanding hedged language in management commentary, and distinguishing between signal and noise. Claude performs well on these tasks relative to alternatives tested.

**Anti-hallucination guardrails**: Claude's training includes Constitutional AI techniques that reduce confident confabulation. For financial use cases where fabricated data (insider transactions, earnings figures) can cause real harm, this matters.

**Context length**: The overnight scanner sends data from 8 APIs, technical indicators computed in Python, and a performance memory of recent picks. This requires substantial context. Claude's context window handles this without truncation.

**Cost efficiency**: The numeric pre-filter (volume spike, price move, RSI extremes, Bollinger breakouts) runs before Claude is called. This cuts API usage 60-70% by sending only interesting tickers to the model.

**Self-correction loop**: The morning scorecard feeds Claude's prior performance back into the prompt: win rates, sector breakdowns, confidence calibration. Claude's responsiveness to this feedback allows the system to improve over time without retraining.

## Model Selection by Task
- **claude-haiku**: High-volume tasks — ticker pre-screening, news sentiment scoring, quick summarization. Low latency, low cost.
- **claude-sonnet**: High-stakes tasks — overnight scanner final analysis, portfolio research enrichment, complex regime commentary. Better reasoning quality justified by lower call frequency.

## Consequences
- Dependency on Anthropic API availability and pricing
- Claude API costs are tracked per scan (input/output tokens + USD) via the `/overnight/history` endpoint
- The system degrades gracefully: if the Claude call fails, the quantitative signal is still returned without the AI enrichment layer
- All prompts live in `backend/prompts/` as `.txt` files — they are versioned and reviewable, not embedded in code
