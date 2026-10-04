from pathlib import Path


path = Path("/opt/kiwoom/current/refresh_api.py")
source = path.read_text()

source = source.replace(
    "ALLOWED_ORIGIN = 'https://moa-invest-sep22.erickang78.chatgpt.site'\n",
    "ALLOWED_ORIGIN = 'https://moa-invest-sep22.erickang78.chatgpt.site'\n"
    "ALLOWED_ORIGINS = {ALLOWED_ORIGIN, 'https://example.invalid'}\n",
)
source = source.replace(
    "        if self.headers.get('Origin') == ALLOWED_ORIGIN:\n"
    "            self.send_header('Access-Control-Allow-Origin', ALLOWED_ORIGIN)\n",
    "        origin = self.headers.get('Origin')\n"
    "        if origin in ALLOWED_ORIGINS:\n"
    "            self.send_header('Access-Control-Allow-Origin', origin)\n",
)
source = source.replace(
    "if self.headers.get('Origin') != ALLOWED_ORIGIN:",
    "if self.headers.get('Origin') not in ALLOWED_ORIGINS:",
)

source = source.replace(
    "from price_api import domestic_quote, us_search, us_quote, chart\n",
    "from price_api import domestic_quote, us_search, us_quote, chart\n"
    "from trading_api import route as trade_route\n",
)
source = source.replace(
    "        is_chart_us = self.path == '/v1/market/chart/us'\n",
    "        is_chart_us = self.path == '/v1/market/chart/us'\n"
    "        is_trade = self.path in ('/v1/trade/preview', '/v1/trade/submit')\n",
)
source = source.replace(
    "        if not mode and not is_flow and not is_coin and not is_price:\n",
    "        if not mode and not is_flow and not is_coin and not is_price and not is_trade:\n",
)
source = source.replace(
    "        if is_flow or is_price:\n",
    "        if is_flow or is_price or is_trade:\n",
)
source = source.replace(
    "        if not is_price:\n",
    "        if not is_price and not is_trade:\n",
)
source = source.replace(
    "        try:\n            if is_quote_domestic:\n",
    "        try:\n            if is_trade:\n"
    "                return self._json(200, trade_route(self.path, body))\n"
    "            if is_quote_domestic:\n",
)
source = source.replace(
    "'quote_failed' if is_price else ('upbit_refresh_failed' if is_coin else 'broker_refresh_failed')",
    "'trade_failed' if is_trade else ('quote_failed' if is_price else ('upbit_refresh_failed' if is_coin else 'broker_refresh_failed'))",
)
source = source.replace(
    "from trading_api import route as trade_route\nfrom trading_api import route as trade_route\n",
    "from trading_api import route as trade_route\n",
)
source = source.replace(
    "        is_trade = self.path in ('/v1/trade/preview', '/v1/trade/submit')\n" * 2,
    "        is_trade = self.path in ('/v1/trade/preview', '/v1/trade/submit')\n",
)
source = source.replace(
    "ALLOWED_ORIGINS = {ALLOWED_ORIGIN, 'https://example.invalid'}\n" * 2,
    "ALLOWED_ORIGINS = {ALLOWED_ORIGIN, 'https://example.invalid'}\n",
)

required = (
    "from trading_api import route as trade_route",
    "is_trade = self.path in",
    "trade_route(self.path, body)",
    "ALLOWED_ORIGINS = {ALLOWED_ORIGIN",
)
if not all(item in source for item in required):
    raise SystemExit("trade route patch failed")

compile(source, str(path), "exec")
path.write_text(source)
print("TRADE_ROUTES_UPDATED")
