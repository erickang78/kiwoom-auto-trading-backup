from pathlib import Path
from datetime import datetime
import sys

def patch(path,script):
 old=path.read_text();tag='<script id="account-number-placement-module">';block=tag+'\n'+script+'\n</script>'
 if tag in old:
  a=old.index(tag);b=old.index('</script>',a)+len('</script>');new=old[:a]+block+old[b:]
 else:
  assert 'id="stock-navigation-module"' in old
  new=old.replace('</body>',block+'</body>',1)
 backup=path.with_name(path.name+'.before-account-number-placement-'+datetime.now().strftime('%Y%m%d%H%M%S'));backup.write_text(old)
 tmp=path.with_name(path.name+'.returns-new');tmp.write_text(new);tmp.chmod(path.stat().st_mode & 0o777);tmp.replace(path)
 print('ACCOUNT_NUMBER_PLACEMENT_UPDATED',backup.name)

if __name__=='__main__':patch(Path(sys.argv[1]),Path(sys.argv[2]).read_text())
