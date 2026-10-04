"""Replace only the shared real trading UI after checking its prior checksum."""
from pathlib import Path
import datetime, hashlib, shutil, sys
p=Path('/opt/kiwoom/dashboard-source/dist/index.html')
s=p.read_text();tag='<script id="auto-trading-execution-module">';assert s.count(tag)==1
a=s.index(tag)+len(tag);b=s.index('</script>',a)
old=s[a:b].strip();assert hashlib.sha256(old.encode()).hexdigest()==sys.argv[2], 'UI changed; deployment stopped'
u=Path(sys.argv[1]).read_text().strip();assert "mount(document.querySelector('#panel-signal-validation'),true)" in u
backup=str(p)+'.before-real-holdings-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S');shutil.copy2(p,backup)
p.write_text(s[:a]+'\n'+u+'\n'+s[b:]);print('REAL_HOLDINGS_UPDATED',backup,hashlib.sha256(u.encode()).hexdigest())
