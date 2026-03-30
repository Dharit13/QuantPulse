# ADR-003: Human-in-the-Loop Execution, Not Automated Trading

## Status
Active (permanent architectural decision, not a temporary constraint)

## Context
The technical capability to connect to a brokerage API (Alpaca, Interactive Brokers, etc.) and automate trade execution exists and would take ~2 days to implement. The question was whether to build QuantPulse as an automated trading system or as an advisory system.

## Decision
QuantPulse is advisory-only. It does not connect to any brokerage. It does not place, modify, or cancel orders. The human executes every trade.

## Reasoning

**Model uncertainty**: Signal quality estimates, Kelly fractions, and regime classifications all carry uncertainty bounds that widen significantly in edge cases. Automating on uncertain estimates scales mistakes. When the model is wrong about a regime transition or a cointegration breakdown, an automated system executes at scale before the error is detected. An advisory system gives the human a chance to notice something looks off.

**Tail risk**: The scenarios that matter most — flash crashes, earnings surprises, liquidity crises, data source failures — are exactly the scenarios where automated systems fail in correlated ways. These are also the scenarios where the system's training distribution is thinnest.

**Accountability and understanding**: If the human places the trade, the human had to read the signal card, understand the rationale, and decide to act. This builds understanding of what the system is doing and why. Automated systems build dependency — operators stop understanding what's happening and lose the ability to intervene intelligently.

**Regulatory clarity**: Advisory tools occupy a clear legal category. Automated trading systems require different compliance frameworks depending on jurisdiction, account type, and strategy.

**Alignment analogy**: This is the same principle behind Constitutional AI and scalable oversight. The system proposes actions with supporting reasoning. The human ratifies before irreversible consequences occur. Autonomy is earned through demonstrated reliability, not assumed from the start.

## What This Means in Practice
- No brokerage API credentials are stored or used
- The dashboard presents signal cards with entry price, stop, target, size recommendation, and supporting evidence
- "Execute" means the human manually places the order in their brokerage account
- The journal module exists for the human to log what they actually traded, enabling outcome tracking

## Consequences
- Slower execution: human latency vs millisecond automation. For strategies with sub-minute edges, this is disqualifying — those strategies are not in scope.
- All five strategies are designed for multi-day to multi-week holding periods where human execution latency is irrelevant.
- The advisory model is the right product for the current phase. If the shadow book produces 2+ years of validated track record with Sharpe > 1.5, the automation question can be revisited.
