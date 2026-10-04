"""Download the Kiwoom US stock master and replace the local JSON atomically."""
import datetime
import json
import os
import time
from pathlib import Path

from broker_read import Client
from credentials import load_credentials

REAL_BASE = "https://api.kiwoom.com"
REAL_CREDENTIALS = Path("/opt/kiwoom/secrets/real-credentials.json")
OUT = Path("/opt/kiwoom/current/us-stock-list.json")
FIELDS = ("stk_cd", "stk_nm", "stk_enm", "stex_tp", "mkgb")


def download():
    client = Client(REAL_BASE)
    client.authenticate(*load_credentials(REAL_CREDENTIALS))
    rows = []
    continuation = None
    for _ in range(100):
        headers = {"api-id": "usa10099", "authorization": "Bearer " + client.token}
        if continuation:
            headers.update({"cont-yn": continuation[0], "next-key": continuation[1]})
        data, next_page = client._post("/api/us/stkinfo", {"stex_tp": "%"}, headers)
        rows.extend(data.get("list") or [])
        if next_page[0] != "Y":
            break
        if not next_page[1] or next_page == continuation:
            raise RuntimeError("invalid_pagination")
        continuation = next_page
        time.sleep(0.25)
    else:
        raise RuntimeError("incomplete_stock_list")
    stocks = [{key: row.get(key, "") for key in FIELDS} for row in rows]
    if not stocks:
        raise RuntimeError("empty_stock_list")
    return stocks


def main():
    stocks = download()
    payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "count": len(stocks),
        "stocks": stocks,
    }
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temp, OUT)
    print(f"{datetime.date.today().isoformat()} updated {len(stocks)} US stocks")


if __name__ == "__main__":
    main()
