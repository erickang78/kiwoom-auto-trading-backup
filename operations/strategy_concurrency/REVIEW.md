# Strategy concurrency — deployed 2026-10-06

This branch adds independent real-trading portfolios for trend, breakout, pullback,
reversion and momentum. It was built over source read from the live server, retaining
its live valuation proposal/confirmed-fill separation, sale-profit calculation,
10/4/1 real-order quantity tiers and ten-position limit. Virtual-trading rules remain
unchanged. `server-sync` and the candidate builder's `server-baseline/current` carry
the same affected application files. No live DB, token, credentials or account rows
are included in the patch.

## Budget and ownership contract

- `(market,strategy)` is the portfolio key; selected status/start/stop/restart,
  holdings, orders and cumulative/period returns use that scope. Daily history
  retains the five-strategy chart, calculated from each strategy’s own positions.
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

## Offline migration and rollback procedure

The application refuses a legacy market-only schema at startup. Migration must be
an explicit offline operation with a separate backup, rather than being triggered
by a status request. The authorized deployment below followed this procedure.

1. Before deployment, re-fetch the live source and compare hashes with the
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

Final local results: `server-sync` 275 tests passed; `server-baseline/current`
260 tests passed; multi-user/login/candidate suite 37 tests passed; repository secret
checks 5 tests passed; Node strategy UI integration and all three affected script
syntax checks passed. The new strategy safety suite includes 25 synthetic tests.
Candidate build/preflight passed, and candidate mutation routes returned 403 in
synthetic handler tests. These are local checks, not live multi-strategy execution.

## Production deployment record

Application commit `0bd3f1de28d8c82e9f9b02e58260a602fadc3e1d` was deployed
on 2026-10-06. Live baseline hashes matched before replacement. Only
`auto_trading.py`, `strategy_budget.py`, `auto_recovery.py`,
`auto_performance_history.py` and the inner `auto-trading-execution-module`
HTML script changed. All unrelated HTML bytes were preserved.

A network-isolated, credential/state-inaccessible transient server test ran
234 synthetic tests successfully before stopping production writers. A preparation
wrapper variable error occurred after those tests, before any production change;
the successful saved result and unchanged baseline were verified before continuing.

Deployment SSM command `607a7799-aa4c-43b7-b523-530a779218e2` completed
Success/exit 0. Private backup directory:
`/opt/kiwoom/.strategy-backup-20261006T022743Z` (0700), with
`auto-trading.sqlite3` (0600). Original portfolio rows and all original intent
columns/IDs/payload/status/dedup and intent failures were compared exactly with
writers stopped, before resuming. DB integrity passed; KR cap and breakout
allocation remain 2,400,000 KRW; US cap remains 1,000 USD. New strategy rows
are disabled with zero allocations. No new strategy was started.

Only the existing API, real performance and real auto-trading writer services
were stopped/restarted, restoring active/enabled state. Caddy, dashboard,
shared-login, signal-validation and Kakao service PIDs remained unchanged.
No credentials, shared authentication/configuration, pilot environment or
service unit definitions changed.

Final read-only SSM command `8d1f7272-6436-4740-aa0f-a085c7153388` completed
Success/exit 0 at 2026-10-06 11:33 KST: all five selected KR statuses returned
200 with five-series history; stock-list was verified 200 during deployment;
public HTTPS login returned 200; DB integrity and private backup permissions
passed. Staging was removed. Existing breakout execution resumed under the
previous enabled state; no live test order or new strategy start was issued.

`deploy.py` implements private staging, isolated synthetic tests, offline backup/
migration and exact preservation checks, atomic installation, writer-state
restoration, and pre-resume rollback. It refuses stale DB restoration after
worker resumption. Do not rerun the completed deployment command.
