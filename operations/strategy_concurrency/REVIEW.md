# Strategy concurrency candidate — not deployed

This branch adds independent real-trading portfolios for trend, breakout, pullback,
reversion and momentum. It was built over source read from the live server, retaining
its live valuation proposal/confirmed-fill separation, sale-profit calculation,
10/4/1 real-order quantity tiers and ten-position limit. Virtual-trading rules remain
unchanged. `server-sync` and the candidate builder's `server-baseline/current` carry
the same affected application files. No live DB, token, credentials or account rows
are included in the patch.

## Budget and ownership contract

- `(market,strategy)` is the portfolio key; selected status/start/stop/restart,
  holdings, orders, cumulative/period returns and daily history use that scope.
- The existing market budget becomes `market_budgets.total_cap`. Legacy KR cap and
  breakout allocation remain exactly 2,400,000 when that is the legacy value; US
  amounts remain USD. The existing active flag, revisions, start timestamps, JSON
  data, observations, holdings and signal dedup are copied verbatim. Other strategies
  are disabled with allocation zero. No strategy is automatically started.
- `action=allocate` changes only the selected allocation, including while running.
  Sum allocations cannot exceed the market cap. The lower bound is confirmed
  position cost plus each remaining pending buy's limit price × quantity × 1.01.
  Broker-confirmed remaining quantities account for partial cancellation; legacy
  unconfirmed orders conservatively reserve requested minus applied quantity. Zero
  is allowed only for a stopped strategy without committed exposure.
- Starting requires positive allocation and explicit confirmation. Allocation changes
  bump strategy and market revisions; stale proposals cannot submit after an edit.
- Ten positions/reservations is a per-strategy limit. Ownership and pending buy
  reservations span all strategies, including stopped ones. Actual account holdings
  and pending broker orders also exclude a new buy. Broker account data currently
  aggregates quantities by code, so its exclusion is conservatively code-wide within
  the market; the durable strategy ownership key includes exchange and code.
- Global gate then SQLite `BEGIN IMMEDIATE` serializes reservation and execution.
  An unknown intent is durable before any send; accepted/partial/unknown/
  reconcile_error orders retain reservations across restart. Any market unknown
  order blocks new buys. Selling requires the selected strategy's confirmed holdings
  and matching actual-account/sellable quantity. Cash checks and 1% margin remain.
- Stop does not cancel orders or liquidate holdings. Stopped or globally paused
  portfolios reconcile existing orders using broker reads only, with no scan, quote
  proposal or order submission. A global pause leaves all strategy enabled flags intact.
- UI exposes selected-strategy allocation save/start/stop and market cap/allocation/
  committed/holdings overview. Starting still has a separate confirmation step.

## Future migration and rollback (separate deployment authorization required)

The application refuses a legacy market-only schema at startup. Migration must be
an explicit offline operation with a separate backup, rather than being triggered
by a status request. No commands below were run on production for this task.

1. Before a future deployment, re-fetch the live source and compare hashes with the
   captured baseline; preserve later live edits. Back up only affected code/UI and
   unit definitions. Identify and stop **all auto DB writers** for the maintenance
   window, including API requests, real worker and performance snapshot worker.
   Do not alter strategy flags, allocations, holdings, intents or trading-control data.
2. With writers confirmed stopped, execute as the existing service UID:
   `python3 strategy_budget.py migrate --database <auto-db> --backup <new-private-backup> --writers-stopped`
   This creates a 0600 SQLite backup before transactional migration. The untouched
   old portfolio rows additionally remain in `portfolios_legacy_v1`. Verify integrity,
   exact old rows, intent/dedup counts, KR cap/allocation, inactive zero allocations
   and US currency before replacing code. Do not log DB contents or credentials.
3. Review and atomically install only changed files with original ownership/mode.
   Reconcile existing orders before resuming the previously enabled strategy. A
   pending broker order and restart timing must be accounted for, even during the
   maintenance window. No new strategy is to be enabled by deployment.
4. On a pre-resume failure, restore previous code and the full backup with writers
   still stopped:
   `python3 strategy_budget.py rollback --database <auto-db> --backup <private-backup> --writers-stopped`
   Rollback refuses existing WAL/SHM/journal sidecars, verifies integrity, preserves
   the destination UID/GID/mode, and atomically restores the old database. Return the
   old code before restarting old services.
5. **After any broker activity or new fill recording, never restore a stale DB backup.**
   Preserve the latest ledger and stop new submissions for a reviewed reconciliation/
   reverse migration. A raw pre-migration DB restore would discard order/fill evidence.

Candidate build/preflight remain local-only and retain the pilot read-only API guard:
allocation/start/stop and broker routes stay blocked. No candidate services were
installed, enabled, started or exposed on the server.

## Verification

Synthetic tests exercise legacy byte-exact preservation and offline rollback,
independent control of all five strategies, allocation races and committed floors,
same-symbol simultaneous proposals, manual/stopped holdings, pending and unknown
reservations, stale proposal rejection, ten-slot scope, partial fills while stopped,
global pause, selected sell quantity, and isolated reports/history. Existing tests
were aligned with the live real 10/4/1 rules and conservative origin classification.
The Node DOM smoke checks editable running allocations, overview, selected stop,
strategy switching and explicit start confirmation. All broker functions in trading
smokes are synthetic mocks; no production orders or data mutations are used.

Final local results: `server-sync` 272 tests passed; `server-baseline/current`
257 tests passed; multi-user/login/candidate suite 37 tests passed; repository secret
checks 5 tests passed; Node strategy UI integration and all three affected script
syntax checks passed. The new strategy safety suite includes 22 synthetic tests.
Candidate build/preflight passed, and candidate mutation routes returned 403 in
synthetic handler tests. These are local checks, not live multi-strategy execution.
