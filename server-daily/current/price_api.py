from zoneinfo import ZoneInfo
"""Read-only domestic and US stock search/quote helpers."""
import datetime
import json
import re
import threading
from pathlib import Path

from broker_read import Client
from credentials import load_credentials

REAL_BASE = "https://api.kiwoom.com"
REAL_CREDENTIALS = Path("/opt/kiwoom/secrets/real-credentials.json")
US_STOCK_LIST = Path("/opt/kiwoom/current/us-stock-list.json")
_CACHE = {"mtime_ns": 0, "rows": []}
_LOCK = threading.Lock()


def _client():
    client = Client(REAL_BASE)
    client.authenticate(*load_credentials(REAL_CREDENTIALS))
    return client


def _call(client, api_id, path, body, continuation=None):
    headers = {"api-id": api_id, "authorization": "Bearer " + client.token}
    if continuation:
        headers.update({"cont-yn": continuation[0], "next-key": continuation[1]})
    return client._post(path, body, headers)


def _timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def domestic_quote(code):
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        raise ValueError("invalid_stock_code")
    data, _ = _call(_client(), "ka10001", "/api/dostk/stkinfo", {"stk_cd": code})
    fields = (
        "stk_cd", "stk_nm", "cur_prc", "pred_pre", "flu_rt", "trde_qty",
        "open_pric", "high_pric", "low_pric", "base_pric", "mac",
    )
    return {
        "market": "KR",
        "quote": {key: data.get(key, "") for key in fields},
        "retrieved_at": _timestamp(),
    }


def _us_rows():
    with _LOCK:
        try:
            mtime_ns = US_STOCK_LIST.stat().st_mtime_ns
        except FileNotFoundError as exc:
            raise RuntimeError("us_stock_list_missing") from exc
        if _CACHE["mtime_ns"] == mtime_ns and _CACHE["rows"]:
            return _CACHE["rows"]
        payload = json.loads(US_STOCK_LIST.read_text(encoding="utf-8"))
        rows = payload.get("stocks") if isinstance(payload, dict) else None
        if not rows:
            raise RuntimeError("empty_stock_list")
        _CACHE.update(mtime_ns=mtime_ns, rows=rows)
        return rows


def us_search(query):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 80:
        raise ValueError("invalid_query")
    wanted = query.strip().casefold()
    matches = [
        row for row in _us_rows()
        if any(wanted in str(row.get(key, "")).casefold() for key in ("stk_cd", "stk_nm", "stk_enm"))
    ]
    matches.sort(key=lambda row: (str(row.get("stk_cd", "")).casefold() != wanted, str(row.get("stk_cd", ""))))
    fields = ("stk_cd", "stk_nm", "stk_enm", "stex_tp", "mkgb")
    return {
        "market": "US",
        "results": [{key: row.get(key, "") for key in fields} for row in matches[:30]],
        "total": len(matches),
        "retrieved_at": _timestamp(),
    }


def us_quote(code, exchange):
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9.\-/]{1,12}", code):
        raise ValueError("invalid_stock_code")
    if exchange not in ("NA", "ND", "NY"):
        raise ValueError("invalid_exchange")
    data, _ = _call(
        _client(), "usa20100", "/api/us/mrkcond", {"stex_tp": exchange, "stk_cd": code}
    )
    fields = (
        "stk_cd", "stk_nm", "stk_enm", "stex_tp", "cur_prc", "pred_pre",
        "flu_rt", "acc_trde_qty", "open_pric", "high_pric", "low_pric",
        "base_close_pric", "curr_unit", "base_exrt",
    )
    return {
        "market": "US",
        "quote": {key: data.get(key, "") for key in fields},
        "retrieved_at": _timestamp(),
    }


def chart(market, code, exchange="", period="day"):
    periods = {"1m": "1", "5m": "5", "15m": "15", "60m": "60",
               "day": None, "week": None, "month": None}
    if period not in periods:
        raise ValueError("invalid_period")
    minute = period.endswith("m")
    if market == "KR":
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
            raise ValueError("invalid_stock_code")
        base_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y%m%d")
        api_id, row_key = {
            "day": ("ka10081", "stk_dt_pole_chart_qry"),
            "week": ("ka10082", "stk_stk_pole_chart_qry"),
            "month": ("ka10083", "stk_mth_pole_chart_qry"),
        }.get(period, ("ka10080", "stk_min_pole_chart_qry"))
        body = {"stk_cd": code, "upd_stkpc_tp": "1"}
        if minute:
            body["tic_scope"] = periods[period]
        else:
            body["base_dt"] = base_dt
        data, _ = _call(_client(), api_id, "/api/dostk/chart", body)
        rows = data.get(row_key) or []
        volume_key = "trde_qty"
    elif market == "US":
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9.\-/]{1,12}", code):
            raise ValueError("invalid_stock_code")
        if exchange not in ("NA", "ND", "NY"):
            raise ValueError("invalid_exchange")
        start = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
        api_id = {"day": "usa06012", "week": "usa06013", "month": "usa06014"}.get(period, "usa06011")
        body = {"stex_tp": exchange, "stk_cd": code, "strt_dt": start,
                "upd_stkpc_tp": "1", "exrt_appl_tp": "0"}
        if minute:
            body["tic_scope"] = periods[period]
        data, _ = _call(_client(), api_id, "/api/us/chart", body)
        rows = data.get("result_list") or []
        volume_key = "trde_qty" if minute else "acc_trde_qty"
    else:
        raise ValueError("invalid_market")
    bars = [
        {"date": row.get("cntr_tm" if minute else "dt", ""), "open": row.get("open_pric", ""),
         "high": row.get("high_pric", ""), "low": row.get("low_pric", ""),
         "close": row.get("cur_prc", ""), "volume": row.get(volume_key, "")}
        for row in rows[:60]
    ]
    bars.sort(key=lambda row: row["date"])
    return {"market": market, "code": code, "period": period, "bars": bars,
            "retrieved_at": _timestamp()}


def daily_chart(market, code, exchange=""):
    """Backward-compatible daily chart entry point."""
    return chart(market, code, exchange, "day")
