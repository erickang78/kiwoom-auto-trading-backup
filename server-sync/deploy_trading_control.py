"""Patch current server sources; never replace unrelated live changes."""
from pathlib import Path
import datetime
import json
import shutil


def replace_once(source, old, new):
    assert source.count(old) == 1, 'Unexpected source anchor: ' + old[:70]
    return source.replace(old, new)


def patch_api(source):
    source = replace_once(source, '        is_price = ', "        is_trading_control = self.path == '/v1/trading/control'\n        is_price = is_trading_control or ")
    return replace_once(source, '            if is_signal_validation:\n', "            if is_trading_control:\n                from trading_control import status as trading_status\n                return self._json(200, trading_status(body.get('action', 'status')))\n            if is_signal_validation:\n")


def patch_html(source, ui, signal_ui):
    tag='<script id="signal-validation-module">'
    assert source.count(tag)==1 and 'id="trading-control-module"' not in source
    start=source.index(tag)+len(tag);end=source.index('</script>',start)
    source=source[:start]+'\n'+signal_ui+'\n'+source[end:]
    return replace_once(source,'</body>','<script id="trading-control-module">\n'+ui+'\n</script></body>')


def deploy(payload):
    root=Path('/opt/kiwoom/current');api=root/'refresh_api.py';html=Path('/opt/kiwoom/dashboard-source/dist/index.html')
    # Hash preconditions protect live backend edits since local synchronization.
    import hashlib
    for name in ('trading_api.py','signal_validation.py'):
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==payload['base_hashes'][name], 'Live source changed: '+name
    changes=[(api,patch_api(api.read_text())),(html,patch_html(html.read_text(),payload['ui'],payload['signal_ui']))]
    changes += [(root/name,content) for name,content in payload['files'].items()]
    for path,content in changes:
        if path.suffix=='.py':compile(content,str(path),'exec')
    suffix='.before-trading-control-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    for path,_ in changes:
        if path.exists():shutil.copy2(path,path.with_name(path.name+suffix))
    for path,content in changes:
        tmp=path.with_name(path.name+'.control-new');tmp.write_text(content)
        if path.exists():tmp.chmod(path.stat().st_mode & 0o777)
        tmp.replace(path)
    print('TRADING_CONTROL_DEPLOYED',suffix)

if __name__=='__main__':
    deploy(json.loads(Path('/tmp/trading-control-payload.json').read_text()))
