import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backup_code import capture,secret_values
class CodeBackupTests(unittest.TestCase):
 def test_rejects_known_secret_before_upload(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);source=root/'source.py';source.write_text('value="private-long-sensitive-value"')
   with self.assertRaisesRegex(ValueError,'secret_scan'):capture({'current/source.py':source},root/'out',[b'private-long-sensitive-value'])
 def test_snapshot_is_deterministic(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);source=root/'source.py';source.write_text('print("hello")')
   for name in ('a','b'):
    destination=root/name;destination.mkdir();self.assertEqual(capture({'current/source.py':source},destination,[]),1)
   self.assertEqual((root/'a/manifest.json').read_bytes(),(root/'b/manifest.json').read_bytes())
 def test_credentials_selected_without_nonsecret_config(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'config.json';path.write_text(json.dumps({'region':'ap-northeast-2','credentials':'/opt/secrets/credentials.json','secret_access_key':'private-long-sensitive-value'}))
   values=secret_values(directory);self.assertIn(b'private-long-sensitive-value',values);self.assertNotIn(b'ap-northeast-2',values)
if __name__=='__main__':unittest.main()
