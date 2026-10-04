from pathlib import Path
import shutil, datetime

def deploy(module):
    p = Path('/opt/kiwoom/dashboard-source/dist/index.html')
    s = p.read_text()
    assert 'interactive-quote-chart-module' not in s
    suffix = '.before-interactive-chart-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    shutil.copy2(p, str(p) + suffix)
    p.write_text(s.replace('</body>', '<script id="interactive-quote-chart-module">\n' + module + '\n</script></body>'))
    print('INTERACTIVE_CHART_UPDATED', suffix)

if __name__ == '__main__':
    deploy(Path('/tmp/interactive-quote-chart.js').read_text())
