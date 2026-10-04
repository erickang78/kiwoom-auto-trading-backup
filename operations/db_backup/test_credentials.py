import tempfile,unittest,subprocess,os
from pathlib import Path
from credential_backup import snapshot_credentials
from backup import encrypt
from restore_credentials_test import restore
class CredentialBackupTests(unittest.TestCase):
 def test_roundtrip_private_files(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'source';source.mkdir();(source/'token').write_text('test-private-value');(source/'settings.json').write_text('{"api_key":"fixture-value"}')
   key=root/'key';cert=root/'cert';password=root/'password';password.write_text('fixture-only')
   subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-keyout',str(key),'-out',str(cert),'-passout','file:'+str(password),'-subj','/CN=Test/','-days','1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   archive,count=snapshot_credentials(source,root);self.assertEqual(count,2)
   encrypted=root/'backup.cms';encrypt(archive,cert,encrypted)
   dest=root/'restored';result=restore(encrypted,key,password,dest)
   self.assertTrue(result['verified']);self.assertFalse(result['installed'])
   for p in source.iterdir():
    restored=dest/'secrets'/p.name;self.assertEqual(restored.read_bytes(),p.read_bytes());self.assertEqual(restored.stat().st_mode&0o777,0o600)
   with self.assertRaises(ValueError):restore(encrypted,key,password,dest)
 def test_symlink_refused(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'source';source.mkdir();target=root/'other';target.write_text('fixture');(source/'link').symlink_to(target)
   with self.assertRaises(OSError):snapshot_credentials(source,root)
if __name__=='__main__':unittest.main()
