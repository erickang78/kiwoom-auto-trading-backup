"""UI-only signal comparison deployment. No broker calls or DB writes."""
from pathlib import Path
import datetime
import hashlib
import shutil
import sys


def patch(path, script, expected_hash):
    old = path.read_text()
    tag = '<script id="signal-validation-module">'
    assert old.count(tag) == 1
    start = old.index(tag) + len(tag)
    end = old.index('</script>', start)
    assert hashlib.sha256(old[start:end].strip().encode()).hexdigest() == expected_hash, 'Live UI changed; re-read before deployment'
    assert 'data-signal-type="real"' in script and 'function actualFor' in script
    backup = path.with_name(path.name + '.before-signal-comparison-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S'))
    shutil.copy2(path, backup)
    updated = old[:start] + '\n' + script.strip() + '\n' + old[end:]
    tmp = path.with_name(path.name + '.comparison-new')
    tmp.write_text(updated)
    shutil.copymode(path, tmp)
    tmp.replace(path)
    assert path.read_text() == updated
    print('COMPARISON_DEPLOYED', backup.name, hashlib.sha256(script.strip().encode()).hexdigest())


if __name__ == '__main__':
    patch(Path(sys.argv[1]), Path(sys.argv[2]).read_text(), sys.argv[3])
