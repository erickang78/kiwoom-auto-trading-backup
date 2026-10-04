import datetime,gzip,json,py_compile,sqlite3,subprocess,tempfile
from pathlib import Path
ROOT=Path('/opt/kiwoom/current');PAGE=Path('/opt/kiwoom/dashboard-source/dist/index.html')
def deploy(payload):
 old=(ROOT/'auto_trading.py').read_text();anchor="    action = body.get('action', 'status')\n"
 assert old.count(anchor)==1 and "if action == 'performance':" not in old
 new=old.replace(anchor,anchor+payload['branch'])
 page=PAGE.read_text();assert 'id="profit-report-module"' not in page
 html=page.replace('</body>','<script id="profit-report-module">\n'+payload['ui']+'\n</script></body>')
 with tempfile.TemporaryDirectory() as directory:
  tmp=Path(directory)
  for name in ['real_profit_report.py','test_real_profit_report.py']:(tmp/name).write_text(payload[name])
  (tmp/'auto_trading.py').write_text(new)
  for file in tmp.glob('*.py'):py_compile.compile(str(file),doraise=True)
  subprocess.run(['python3','-m','unittest','test_real_profit_report.py'],cwd=tmp,check=True)
 suffix='.before-profit-report-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
 (ROOT/('auto_trading.py'+suffix)).write_text(old);PAGE.with_name(PAGE.name+suffix).write_text(page)
 files={ROOT/'auto_trading.py':new,ROOT/'real_profit_report.py':payload['real_profit_report.py'],ROOT/'test_real_profit_report.py':payload['test_real_profit_report.py'],PAGE:html}
 try:
  for file,text in files.items():
   temp=file.with_suffix(file.suffix+'.next');temp.write_text(text);temp.replace(file)
  subprocess.run(['systemctl','restart','kiwoom-refresh'],check=True)
  subprocess.run(['systemctl','is-active','kiwoom-refresh','moa-auto-trading'],check=True)
 except Exception:
  (ROOT/'auto_trading.py').write_text(old);PAGE.write_text(page);subprocess.run(['systemctl','restart','kiwoom-refresh']);raise
 print('PROFIT_REPORT_DEPLOYED',suffix)
