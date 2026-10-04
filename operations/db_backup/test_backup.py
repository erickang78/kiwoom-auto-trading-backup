import datetime as dt, json, sqlite3, subprocess, tempfile, unittest
from pathlib import Path
from backup import DATABASES,snapshot,encrypt,object_keys,upload,signed_request
from restore_test import restore
class BackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys=tempfile.TemporaryDirectory();root=Path(cls.keys.name);cls.key=root/'key.pem';cls.cert=root/'cert.pem';cls.passphrase=root/'pass'
        cls.passphrase.write_text('test-only-passphrase')
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-keyout',str(cls.key),'-out',str(cls.cert),'-passout','file:'+str(cls.passphrase),'-subj','/CN=Test/','-days','1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    @classmethod
    def tearDownClass(cls):cls.keys.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.state=self.root/'state';self.state.mkdir();self.stage=self.root/'stage';self.stage.mkdir()
        schemas={
            'auto-trading.sqlite3':"CREATE TABLE portfolios(market TEXT, enabled INTEGER);INSERT INTO portfolios VALUES('KR',1);CREATE TABLE intents(id INTEGER PRIMARY KEY,filled INTEGER);INSERT INTO intents VALUES(1,5);",
            'signal-validation.sqlite3':"CREATE TABLE state(id INTEGER, enabled INTEGER);INSERT INTO state VALUES(1,1);CREATE TABLE events(id INTEGER PRIMARY KEY,data TEXT);INSERT INTO events VALUES(1,'{}');",
            'trading-control.sqlite3':'CREATE TABLE control(id INTEGER,enabled INTEGER);INSERT INTO control VALUES(1,1);',
            'manual-orders.sqlite3':'CREATE TABLE orders(id INTEGER,quantity INTEGER);INSERT INTO orders VALUES(1,2);',
            'kakao-notifications.sqlite3':'''CREATE TABLE settings(id INTEGER,data TEXT);INSERT INTO settings VALUES(1,'{"connected":true}');CREATE TABLE queue(id INTEGER);INSERT INTO queue VALUES(1);'''}
        for name,sql in schemas.items():
            with sqlite3.connect(self.state/name) as db:db.executescript(sql)
    def tearDown(self):self.tmp.cleanup()
    def archive(self):
        plain,manifest=snapshot(self.state,self.stage);encrypted=self.root/'backup.cms';encrypt(plain,self.cert,encrypted);return encrypted,manifest
    def test_roundtrip_preserves_source_and_disables_rehearsal(self):
        before={n:(self.state/n).read_bytes() for n in DATABASES}
        archive,manifest=self.archive();dest=self.root/'restored';result=restore(archive,self.key,self.passphrase,dest)
        self.assertTrue(result['verified']);self.assertEqual(len(manifest['databases']),5)
        for n in DATABASES:self.assertEqual((self.state/n).read_bytes(),before[n])
        with sqlite3.connect(dest/'auto-trading.sqlite3') as db:
            self.assertEqual(db.execute('SELECT enabled FROM portfolios').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT filled FROM intents').fetchone()[0],5)
    def test_missing_database_fails(self):
        (self.state/DATABASES[0]).rename(self.root/'missing')
        with self.assertRaises(FileNotFoundError):snapshot(self.state,self.stage)
    def test_ciphertext_tamper_rejected(self):
        archive,_=self.archive();data=bytearray(archive.read_bytes());data[-20]^=1;archive.write_bytes(data)
        with self.assertRaises(Exception):restore(archive,self.key,self.passphrase,self.root/'bad')
        self.assertTrue((self.root/'bad/RESTORE_FAILED').exists())
    def test_existing_destination_refused(self):
        with self.assertRaises(ValueError):restore('unused',self.key,self.passphrase,self.state)
    def test_kst_retention_categories(self):
        self.assertEqual(len(object_keys(dt.datetime(2026,9,30,16,tzinfo=dt.timezone.utc))),3)
        self.assertEqual(len(object_keys(dt.datetime(2026,10,2,16,tzinfo=dt.timezone.utc))),2)
        self.assertEqual(len(object_keys(dt.datetime(2026,10,2,17,tzinfo=dt.timezone.utc))),1)
    def test_upload_requires_server_checksum_and_version(self):
        self.stage.joinpath('blob').write_bytes(b'encrypted fixture')
        class Response:
            status=200;headers={}
            def __enter__(self):return self
            def __exit__(self,*args):pass
        def good(req,timeout):
            response=Response();response.headers={'x-amz-version-id':'version-1','x-amz-checksum-sha256':req.get_header('X-amz-checksum-sha256')};return response
        config={'bucket':'test-bucket','region':'ap-northeast-2'};credentials={'access_key_id':'test','secret_access_key':'test'}
        result=upload(config,credentials,'hourly/file.cms',self.stage/'blob',good);self.assertEqual(result['version_id'],'version-1')
        with self.assertRaises(RuntimeError):upload(config,credentials,'hourly/file.cms',self.stage/'blob',lambda *a,**k:Response())
if __name__=='__main__':unittest.main()
