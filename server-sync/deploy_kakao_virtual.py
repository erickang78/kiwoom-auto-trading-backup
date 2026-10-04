from pathlib import Path
import hashlib,shutil,datetime,subprocess,json

def deploy(v):
 root=Path('/opt/kiwoom/current');module=root/'kakao_notifications.py';page=Path('/opt/kiwoom/dashboard-source/dist/index.html')
 assert hashlib.sha256(module.read_bytes()).hexdigest()==v['module_hash'],'Live notification module changed'
 h=page.read_text();tag='<script id="kakao-notifications-module">';a=h.index(tag)+len(tag);b=h.index('</script>',a)
 assert hashlib.sha256(h[a:b].strip().encode()).hexdigest()==v['ui_hash'],'Live notification UI changed'
 compile(v['module'],'kakao_notifications.py','exec');compile(v['test'],'test_kakao_notifications.py','exec')
 suffix='.before-kakao-virtual-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S');shutil.copy2(module,str(module)+suffix);shutil.copy2(page,str(page)+suffix)
 subprocess.run(['systemctl','stop','moa-kakao-notifications'],check=True)
 try:
  module.write_text(v['module']);(root/'test_kakao_notifications.py').write_text(v['test'])
  subprocess.run(['python3','-m','unittest','test_kakao_notifications'],cwd=root,check=True)
  subprocess.run(['sudo','-u','ubuntu','python3','-c','import kakao_notifications as k;\nwith k.locked() as db: k.collect_virtual(db,k.SIGNALS)\nprint("KAKAO_STATUS",k.control({"action":"status"}))'],cwd=root,check=True)
  page.write_text(h[:a]+'\n'+v['ui'].strip()+'\n'+h[b:])
  subprocess.run(['systemctl','restart','kiwoom-refresh'],check=True)
 except BaseException:
  shutil.copy2(str(module)+suffix,module);shutil.copy2(str(page)+suffix,page)
  subprocess.run(['systemctl','restart','kiwoom-refresh']);raise
 finally:subprocess.run(['systemctl','start','moa-kakao-notifications'],check=True)
 subprocess.run(['systemctl','is-active','kiwoom-refresh','moa-auto-trading','moa-signal-validation','moa-kakao-notifications'],check=True)
 print('KAKAO_VIRTUAL_UPDATED',suffix)
if __name__=='__main__':deploy(json.loads(Path('/tmp/kakao-virtual-payload.json').read_text()))
