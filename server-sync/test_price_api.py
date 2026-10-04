import unittest
import sys
import json
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

broker_read = types.ModuleType("broker_read")
broker_read.Client = object
credentials = types.ModuleType("credentials")
credentials.load_credentials = lambda path: ("", "")
sys.modules.setdefault("broker_read", broker_read)
sys.modules.setdefault("credentials", credentials)

import price_api


class PriceApiTests(unittest.TestCase):
    @patch.object(price_api, "_client")
    @patch.object(price_api, "_call")
    def test_domestic_quote(self, call, client):
        call.return_value = ({"stk_cd": "005930", "stk_nm": "삼성전자", "cur_prc": "+100"}, None)
        result = price_api.domestic_quote("005930")
        self.assertEqual(result["quote"]["stk_nm"], "삼성전자")
        self.assertEqual(call.call_args.args[1:3], ("ka10001", "/api/dostk/stkinfo"))

    @patch.object(price_api, "_client")
    @patch.object(price_api, "_call")
    def test_us_quote_requires_exchange(self, call, client):
        call.return_value = ({"stk_cd": "AAPL", "stex_tp": "ND", "cur_prc": "+200.00"}, None)
        result = price_api.us_quote("AAPL", "ND")
        self.assertEqual(result["quote"]["cur_prc"], "+200.00")
        self.assertEqual(call.call_args.args[1:3], ("usa20100", "/api/us/mrkcond"))

    def test_invalid_inputs(self):
        for value in ("", "5930", "005930_AL", None):
            with self.assertRaises(ValueError):
                price_api.domestic_quote(value)
        with self.assertRaises(ValueError):
            price_api.us_quote("AAPL", "KRX")

    def test_us_search_reads_stock_list_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "us-stock-list.json"
            path.write_text(json.dumps({"stocks": [
                {"stk_cd": "AAPL", "stk_nm": "애플", "stk_enm": "APPLE INC", "stex_tp": "ND", "mkgb": "NASDAQ"}
            ]}), encoding="utf-8")
            with patch.object(price_api, "US_STOCK_LIST", path):
                price_api._CACHE.update(mtime_ns=0, rows=[])
                result = price_api.us_search("apple")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["stk_cd"], "AAPL")

    @patch.object(price_api, "_client")
    @patch.object(price_api, "_call")
    def test_daily_chart_normalizes_domestic_bars(self, call, client):
        call.return_value = ({"stk_dt_pole_chart_qry": [
            {"dt": "20260924", "open_pric": "+100", "high_pric": "+110", "low_pric": "+90", "cur_prc": "+105", "trde_qty": "1000"}
        ]}, None)
        result = price_api.daily_chart("KR", "005930")
        self.assertEqual(result["bars"][0]["close"], "+105")
        self.assertEqual(call.call_args.args[1:3], ("ka10081", "/api/dostk/chart"))

    @patch.object(price_api, "_client")
    @patch.object(price_api, "_call")
    def test_minute_chart_uses_tick_scope(self, call, client):
        call.return_value = ({"stk_min_pole_chart_qry": [
            {"cntr_tm": "20260924101500", "open_pric": "100", "high_pric": "110", "low_pric": "90", "cur_prc": "105", "trde_qty": "1000"}
        ]}, None)
        result = price_api.chart("KR", "005930", period="15m")
        self.assertEqual(result["period"], "15m")
        self.assertEqual(result["bars"][0]["date"], "20260924101500")
        self.assertEqual(call.call_args.args[1], "ka10080")
        self.assertEqual(call.call_args.args[3]["tic_scope"], "15")

    @patch.object(price_api, "_client")
    @patch.object(price_api, "_call")
    def test_us_weekly_chart(self, call, client):
        call.return_value = ({"result_list": []}, None)
        result = price_api.chart("US", "AAPL", "ND", "week")
        self.assertEqual(result["period"], "week")
        self.assertEqual(call.call_args.args[1], "usa06013")

    def test_chart_rejects_unknown_period(self):
        with self.assertRaises(ValueError):
            price_api.chart("KR", "005930", period="hour")


if __name__ == "__main__":
    unittest.main()
