"""Replace only the signal validation UI; leave workers and records intact."""
from datetime import datetime
from pathlib import Path
import sys


def patch(path, script):
    old = path.read_text()
    tag = '<script id="signal-validation-module">'
    assert old.count(tag) == 1, 'Expected exactly one signal validation module'
    assert 'data-signal-event="BUY"' in script
    assert 'signal-exit-profit' in script and 'signal-exit-loss' in script
    start = old.index(tag) + len(tag)
    end = old.index('</script>', start)
    new = old[:start] + '\n' + script.rstrip() + '\n' + old[end:]
    backup = path.with_name(path.name + '.before-signal-event-tabs-' + datetime.now().strftime('%Y%m%d%H%M%S%f'))
    backup.write_text(old)
    backup.chmod(path.stat().st_mode & 0o777)
    tmp = path.with_name(path.name + '.signal-event-tabs-new')
    tmp.write_text(new)
    tmp.chmod(path.stat().st_mode & 0o777)
    tmp.replace(path)
    assert path.read_text() == new
    print('SIGNAL_EVENT_TABS_UPDATED', backup.name)


if __name__ == '__main__':
    patch(Path(sys.argv[1]), Path(sys.argv[2]).read_text())
