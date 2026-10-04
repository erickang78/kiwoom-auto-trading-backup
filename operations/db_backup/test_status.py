import datetime as dt,json,tempfile,unittest
from pathlib import Path
from backup_status import read_status
class StatusTests(unittest.TestCase):
 def test_status_boundaries_and_redaction(self):
  now=dt.datetime(2026,10,4,tzinfo=dt.timezone.utc)
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'status.json'
   self.assertEqual(read_status(path,now)['status'],'never')
   for age,ok,wanted in [(0,True,'ok'),(7199,True,'ok'),(7200,True,'stale'),(0,False,'failed')]:
    path.write_text(json.dumps({'ok':ok,'last_success':(now-dt.timedelta(seconds=age)).isoformat(),'database_count':5,'objects':['secret']}))
    result=read_status(path,now);self.assertEqual(result['status'],wanted);self.assertNotIn('objects',result)
   path.write_text('{invalid');self.assertEqual(read_status(path,now)['status'],'unavailable')
   path.write_text(json.dumps({'last_success':'2026-10-04T00:00:00'}));self.assertEqual(read_status(path,now)['status'],'unavailable')
