"""Deploy dashboard restart checks without enabling any portfolio or sending an order."""
import datetime as dt
import hashlib,json,os,shutil,sqlite3,subprocess,tempfile
from pathlib import Path
ROOT=Path('/opt/kiwoom/current');PAGE=Path('/opt/kiwoom/dashboard-source/dist/index.html');DB=Path('/opt/kiwoom/state/auto-trading.sqlite3')
def snapshot():
 with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True) as db:
  rows=db.execute('SELECT * FROM portfolios ORDER BY market').fetchall()
  assert all(not r[2] for r in rows),'Deploy only while real portfolios are stopped'
  return rows,db.execute('SELECT * FROM intents ORDER BY id').fetchall()
def deploy(v):
 engine=ROOT/'auto_trading.py';old=engine.read_text();new=old
 for a,b in v['ops']:
  assert new.count(a)==1,'Unexpected engine anchor';new=new.replace(a,b,1)
 page=PAGE.read_text();marker='<script id="auto-trading-execution-module">';assert page.count(marker)==1
 start=page.index(marker);end=page.index('</script>',start);html=page[:start]+marker+'\n'+v['ui']+'\n'+page[end:]
 files={'auto_trading.py':new,**v['files']}
 for name,text in files.items():compile(text,name,'exec')
 before=snapshot();suffix='.before-auto-restart-'+dt.datetime.now().strftime('%Y%m%d%H%M%S')
 with tempfile.TemporaryDirectory(prefix='auto-restart-',dir='/tmp') as folder:
  stage=Path(folder);stage.chmod(0o755)
  for name,text in files.items():(stage/name).write_text(text);(stage/name).chmod(0o644)
  subprocess.run(['sudo','-u','ubuntu','env','PYTHONPATH='+str(ROOT),'PYTHONDONTWRITEBYTECODE=1','/opt/kiwoom/.venv/bin/python','-m','unittest','-q','test_auto_trading','test_quantity_rule','test_auto_recovery','test_auto_performance','test_auto_performance_history'],cwd=stage,check=True)
  if shutil.which('node'):
   (stage/'ui.js').write_text(v['ui']);subprocess.run(['node','--check',str(stage/'ui.js')],check=True)
 assert snapshot()==before and engine.read_text()==old and PAGE.read_text()==page
 targets={ROOT/name:text for name,text in files.items()};targets[PAGE]=html
 originals={path:path.read_bytes() if path.exists() else None for path in targets}
 for path,data in originals.items():
  if data is not None:shutil.copy2(path,str(path)+suffix)
 source=sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True);backup=DB.with_name(DB.name+suffix);target=sqlite3.connect(backup);source.backup(target);source.close();target.close();backup.chmod(0o600)
 try:
  for path,text in targets.items():
   tmp=path.with_name(path.name+'.restart-new');tmp.write_text(text);tmp.chmod(0o644);tmp.replace(path)
  subprocess.run(['systemctl','restart','kiwoom-refresh','moa-auto-trading'],check=True)
  subprocess.run(['systemctl','is-active','kiwoom-refresh','moa-auto-trading','moa-signal-validation','moa-kakao-notifications','moa-dashboard'],check=True)
  assert snapshot()==before,'Trading state changed unexpectedly'
 except BaseException:
  for path,data in originals.items():
   if data is not None:path.write_bytes(data)
   elif path.exists():path.unlink()
  subprocess.run(['systemctl','restart','kiwoom-refresh','moa-auto-trading'],check=False);raise
 print('AUTO_RESTART_DASHBOARD_DEPLOYED',hashlib.sha256(new.encode()).hexdigest(),flush=True)
 print('REAL_PORTFOLIOS_STOPPED_AND_ALL_RECORDS_PRESERVED',len(before[1]),flush=True)
 print('BACKUP',backup,flush=True)
