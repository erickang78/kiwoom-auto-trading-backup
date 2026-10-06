# Actual-cost cumulative performance

`performance` stays gross and unchanged. `performance_net` subtracts only exactly
matched actual broker costs. Missing, stale, duplicate or provisional cost records
remain pending; the UI labels the cumulative return provisional until all filled
intents have final costs. Its denominator is the existing gross cumulative buy
principal. Buy costs follow the lot: pro rata to realized sold quantity, with the
remainder deducted from held valuation. No future selling cost is estimated.
Closed-cycle win rate uses confirmed costs and is provisional with missing costs.
No fills means no defined rate. Histories/period charts stay explicitly gross.

The collector has only a read API allowlist (ka10076, kt00007, kt00009, kt00015).
Today uses date/order/market/exchange/code/side/confirmed quantity/average equality.
Historical matching requires all pages, complete identified fill aggregation,
exact gross amount, one full-account broker order and one transaction in the key,
and a unique automatic intent. kt00015 `cntr_dt` is execution date; `trde_dt` is
not substituted for it. A `*A` symbol marker is accepted only after independent
kt00007 exact order confirmation. Corrections and ambiguous groups are rejected.
Snapshots overwrite the same intent identity rather than accumulate fees again.
Partial observations remain pending. Corrupt/duplicate files do not become zero
costs. Raw responses, credentials and account identifiers are never persisted.

The separate ubuntu oneshot/timer collects every 15 minutes, 08:00–19:45 KST,
and daily 21:00 KST, with full broker requests spaced at least 0.5 seconds.
Unresolved older executions are retried after settlement. It does not submit orders,
control trading, or write trading SQLite databases. US costs remain pending until
an exact actual-cost source is implemented; no KR rate is applied to USD fills.
