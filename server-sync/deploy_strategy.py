"""Run on AWS with sudo after staging /tmp/strategy-payload.json."""
import json
from pathlib import Path

payload = json.loads(Path('/tmp/strategy-payload.json').read_text())
api = Path('/opt/kiwoom/current/refresh_api.py')
html = Path('/opt/kiwoom/dashboard-source/dist/index.html')
original_api, original_html = api.read_text(), html.read_text()
assert 'from strategy_api import screen' not in original_api
assert 'id="strategy-module"' not in original_html
needle = '        is_price = is_quote_domestic'
assert original_api.count(needle) == 1
new_api = 'from strategy_api import screen\n' + original_api
new_api = new_api.replace(needle, "        is_strategy = self.path == '/v1/market/strategy'\n        is_price = is_strategy or is_quote_domestic", 1)
needle = '            if is_trade:\n'
assert new_api.count(needle) == 1
new_api = new_api.replace(needle, "            if is_strategy:\n                return self._json(200, screen(str(body.get('strategy', 'trend'))))\n" + needle, 1)
compile(new_api, str(api), 'exec')
compile(payload['api'], 'strategy_api.py', 'exec')
assert '<head>' in original_html and original_html.count('</body>') == 1
new_html = original_html.replace('<head>', '<head><script>window.moaInitialHash=location.hash;</script>', 1)
new_html = new_html.replace('</body>', '<script id="strategy-module">\n' + payload['ui'] + '\n</script></body>', 1)
for path, old, new in [(api, original_api, new_api), (html, original_html, new_html)]:
    backup = path.with_name(path.name + '.before-strategy')
    assert not backup.exists(), 'Backup already exists; inspect deployment before retrying'
    backup.write_text(old)
Path('/opt/kiwoom/current/strategy_api.py').write_text(payload['api'])
api.write_text(new_api)
html.write_text(new_html)
print('STRATEGY_DEPLOYED')
