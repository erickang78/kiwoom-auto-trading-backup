from pathlib import Path
import datetime,re,shutil
p=Path('/opt/kiwoom/dashboard-source/dist/index.html')
s=p.read_text()
new=re.sub(r'해외주식\s*\(미국\)','해외주식',s).replace('미국주식','해외주식')
assert new!=s,'No old labels remain'
suffix='.before-overseas-labels-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
shutil.copy2(p,str(p)+suffix)
p.write_text(new)
print('OVERSEAS_LABELS_UPDATED',suffix)
