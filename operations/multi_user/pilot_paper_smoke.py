"""Run a synthetic-only paper-trading smoke test in an isolated temp DB."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path

import signal_validation as paper


NOW = dt.datetime(2026, 9, 24, 14, 0, tzinfo=dt.timezone.utc)
SYMBOL = "SYN001"


def scan():
    return {
        "status": "ready",
        "date": "20260923",
        "stocks": [{"code": SYMBOL, "exchange": "ND", "name": "Synthetic", "reason": "smoke"}],
    }


def quote(price: str, volume: str):
    return {"quote": {"cur_prc": price, "acc_trde_qty": volume, "base_exrt": "1300"}}


def run() -> None:
    with tempfile.TemporaryDirectory(prefix="pilot-paper-smoke-") as directory:
        db_path = Path(directory) / "signal-validation.sqlite3"
        paper.cycle(db_path, NOW, lambda _: scan(), lambda *args: quote("50", "100"))
        paper.cycle(db_path, NOW + dt.timedelta(minutes=1), lambda _: scan(), lambda *args: quote("50", "101"))
        bought = paper.status(path=db_path)
        assert bought["orders_enabled"] is False
        assert len(bought["positions"]) == 1 and bought["positions"][0]["code"] == SYMBOL
        assert bought["events"][-1]["kind"] == "BUY"

        paper.cycle(db_path, NOW + dt.timedelta(minutes=2), lambda _: scan(), lambda *args: quote("52.5", "102"))
        sold = paper.status(path=db_path)
        assert not sold["positions"]
        assert sold["events"][0]["kind"] == "SELL"
        assert sold["events"][0]["reason"] == "익절 +5%"

        paper.status("pause", path=db_path)
        def must_not_query(_):
            raise AssertionError("paused paper portfolio must not query a provider")
        paper.cycle(db_path, NOW + dt.timedelta(minutes=3), must_not_query, must_not_query)
        paused = paper.status(path=db_path)
        assert not paused["enabled"]
        assert len(paused["events"]) == 2
        with paper.connect(db_path) as db:
            rows = [json.loads(row[0]) for row in db.execute("SELECT data FROM events")]
            assert all(row["code"] == SYMBOL for row in rows)
        print("synthetic paper smoke passed: BUY, take-profit SELL, pause; isolated temporary database; no broker/network functions")


if __name__ == "__main__":
    run()
