from pathlib import Path
from datetime import datetime

def patch(path,manual,nav):
 old=path.read_text()
 new=old
 for marker,script in [('manual-order-module',manual),('stock-navigation-module',nav)]:
  tag='<script id="'+marker+'">'
  block=tag+'\n'+script+'\n</script>'
  if tag in new:
   start=new.index(tag);end=new.index('</script>',start)+len('</script>')
   new=new[:start]+block+new[end:]
  else:
   assert new.count('</body>')==1
   new=new.replace('</body>',block+'</body>',1)
 backup=path.with_name(path.name+'.before-stock-navigation-'+datetime.now().strftime('%Y%m%d%H%M%S'))
 backup.write_text(old)
 tmp=path.with_name(path.name+'.stock-nav-new');tmp.write_text(new);tmp.chmod(path.stat().st_mode & 0o777);tmp.replace(path)
 print('STOCK_NAVIGATION_UPDATED',backup.name)

if __name__=='__main__':
 import sys
 patch(Path(sys.argv[1]),Path(sys.argv[2]).read_text(),Path(sys.argv[3]).read_text())
