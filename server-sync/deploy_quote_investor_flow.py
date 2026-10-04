from pathlib import Path
import shutil, datetime

def deploy(module):
    p = Path('/opt/kiwoom/dashboard-source/dist/index.html')
    s = p.read_text()
    assert 'last-stock-memory-module' in s
    assert 'quote-investor-flow-module' not in s
    suffix = '.before-quote-investor-flow-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    shutil.copy2(p, str(p) + suffix)
    s = s.replace('</body>', '<script id="quote-investor-flow-module">\n' + module + '\n</script></body>')
    p.write_text(s)
    print('QUOTE_FLOW_UPDATED', suffix)

if __name__ == '__main__':
    deploy(Path('/tmp/quote-investor-flow.js').read_text())
