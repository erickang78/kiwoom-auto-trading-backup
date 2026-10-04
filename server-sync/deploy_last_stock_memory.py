from pathlib import Path
import json,hashlib,shutil,datetime

def deploy(v):
 p=Path('/opt/kiwoom/dashboard-source/dist/index.html');s=p.read_text();tag='<script id="manual-order-module">';a=s.index(tag)+len(tag);b=s.index('</script>',a)
 assert hashlib.sha256(s[a:b].strip().encode()).hexdigest()==v['order_hash'],'Order module changed'
 assert 'last-stock-memory-module' not in s,'Already deployed'
 suffix='.before-last-stock-memory-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S');shutil.copy2(p,str(p)+suffix)
 s=s[:a]+'\n'+v['order'].strip()+'\n'+s[b:];s=s.replace('</body>','<script id="last-stock-memory-module">\n'+v['memory']+'\n</script></body>');p.write_text(s);print('LAST_STOCK_MEMORY_UPDATED',suffix)
if __name__=='__main__':deploy(json.loads(Path('/tmp/last-stock-memory-payload.json').read_text()))
