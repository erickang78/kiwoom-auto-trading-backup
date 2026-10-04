import unittest
from check_repository_secrets import inspect
class SecretScanTests(unittest.TestCase):
    def test_known_secret_detected_without_echo(self):
        reasons=inspect('app.py',b'value=example-private-value',[b'example-private-value'])
        self.assertEqual(reasons,['known private credential'])
    def test_private_and_legacy_paths(self):
        for name in ['.private-backups/key','config/.env','data.sqlite3','server-sync/holdings.png','page.before-change.html','config/real-credentials.json']:
            self.assertTrue(inspect(name,b''),name)
    def test_empty_frontend_token_allowed(self):
        self.assertEqual(inspect('index.html',b"const TOKEN='';"),[])
        self.assertIn('frontend token literal',inspect('index.html',b"const TOKEN='secret';"))
    def test_key_format_detected(self):
        self.assertTrue(inspect('app.txt',b'ghp_'+b'a'*36))
        self.assertTrue(inspect('app.txt',b'AKIA'+b'A'*16))
    def test_regular_source_allowed(self):
        self.assertEqual(inspect('credentials.py',b"key=Path('/opt/kiwoom/secrets/dashboard-token').read_text()"),[])
if __name__=='__main__':unittest.main()
