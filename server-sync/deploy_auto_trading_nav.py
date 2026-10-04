"""Patch only the auto-trading navigation module in the AWS dashboard HTML."""
import datetime
from pathlib import Path
import sys

def patch(path, script):
    old = path.read_text()
    marker = '<script id="auto-trading-nav-module">'
    block = marker + '\n' + script + '\n</script>'
    if marker in old:
        start = old.index(marker)
        end = old.index('</script>', start) + len('</script>')
        new = old[:start] + block + old[end:]
    else:
        assert old.count('</body>') == 1
        assert 'id="strategy-module"' in old and 'id="signal-validation-module"' in old
        new = old.replace('</body>', block + '</body>', 1)
    backup = path.with_name(path.name + '.before-auto-trading-nav-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S'))
    backup.write_text(old)
    temporary = path.with_name(path.name + '.nav-new')
    temporary.write_text(new)
    temporary.chmod(path.stat().st_mode & 0o777)
    temporary.replace(path)
    print('AUTO_TRADING_NAV_UPDATED', backup.name)

if __name__ == '__main__':
    patch(Path(sys.argv[1]), Path(sys.argv[2]).read_text())
