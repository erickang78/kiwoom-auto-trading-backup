"""Run on AWS after staging /tmp/us-strategy-payload.json; preserve other UI edits."""
import datetime
import json
from pathlib import Path

payload = json.loads(Path('/tmp/us-strategy-payload.json').read_text())
root = Path('/opt/kiwoom/current')
api = root / 'refresh_api.py'
html = Path('/opt/kiwoom/dashboard-source/dist/index.html')
price = root / 'price_api.py'
a, h, p = api.read_text(), html.read_text(), price.read_text()
old = "screen(str(body.get('strategy', 'trend')))"
assert a.count(old) == 1
new_a = a.replace(old, "screen(str(body.get('strategy', 'trend')), str(body.get('market', 'KR')))")
start = h.index('<script id="strategy-module">')
end = h.index('</script>', start)
new_h = h[:start] + '<script id="strategy-module">\n' + payload['ui'] + '\n' + h[end:]
old_date = 'start = (datetime.date.today() - datetime.timedelta(days=180)).strftime("%Y%m%d")'
assert p.count(old_date) == 1
new_p = p.replace(old_date, 'start = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")')
new_p = 'from zoneinfo import ZoneInfo\n' + new_p
changes = [(api, new_a), (html, new_h), (price, new_p),
           (root/'strategy_api.py', payload['api']), (root/'us_strategy_api.py', payload['us_api'])]
for path, content in changes:
    if path.suffix == '.py': compile(content, str(path), 'exec')
suffix = '.before-us-strategy-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S')
for path, content in changes:
    if path.exists(): path.with_name(path.name+suffix).write_text(path.read_text())
for path, content in changes:
    temporary = path.with_name(path.name+'.us-new')
    temporary.write_text(content)
    temporary.replace(path)
print('US_STRATEGY_DEPLOYED', suffix)
