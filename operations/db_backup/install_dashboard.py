"""Narrow authenticated status route and footer; no trading worker restart."""
import base64,datetime,hashlib,json,os,shutil,subprocess
from pathlib import Path

def install(bundle,expected_hash):
    gateway=Path('/opt/kiwoom/dashboard_gateway.py');original=gateway.read_text()
    if hashlib.sha256(gateway.read_bytes()).hexdigest()!=expected_hash:raise RuntimeError('gateway_changed_review_required')
    archive=Path('/opt/kiwoom/backups')/('db-status-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    archive.mkdir(mode=0o700);shutil.copy2(gateway,archive/gateway.name)
    for name in ('backup_status.py','dashboard-status.js'):
        target=Path('/opt/kiwoom')/name if name.endswith('.py') else Path('/opt/kiwoom/backup-tools')/name
        target.write_bytes(base64.b64decode(bundle[name]));target.chmod(0o644)
    anchor="        if path.startswith('/v1/') or path=='/health': return self.proxy()"
    insert="""        if path=='/v1/backup/status':
            if not self.authed(): return self.respond(401,json.dumps({'error':'unauthorized'}),'application/json')
            from backup_status import read_status
            return self.respond(200,json.dumps(read_status()),'application/json')
"""
    assert original.count(anchor)==1
    changed=original.replace(anchor,insert+anchor)
    anchor2="            content=content.replace('</body>'"
    assert changed.count(anchor2)==1
    changed=changed.replace(anchor2,"            content=content.replace('</body>','<script>'+Path('/opt/kiwoom/backup-tools/dashboard-status.js').read_text()+'</script></body>')\n"+anchor2)
    compile(changed,str(gateway),'exec');gateway.write_text(changed)
    subprocess.run(['systemctl','restart','moa-dashboard'],check=True)
    print('DASHBOARD_BACKUP_STATUS_INSTALLED; rollback='+str(archive))
