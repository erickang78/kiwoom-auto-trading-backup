import importlib.util, pathlib, unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
PATH=ROOT/'server-baseline/root/dashboard_gateway.py'
with patch.object(pathlib.Path,'read_text',return_value='fixture-auth-key-not-production'):
    spec=importlib.util.spec_from_file_location('gateway',PATH)
    gateway=importlib.util.module_from_spec(spec);spec.loader.exec_module(gateway)
class SecretSeparationTests(unittest.TestCase):
    def render(self,source,authed=True,path='/'):
        handler=object.__new__(gateway.Handler);handler.path=path
        handler.authed=lambda:authed
        result=[];handler.respond=lambda *args,**kwargs:result.append((args,kwargs))
        with patch.object(pathlib.Path,'read_text',return_value=source):handler.do_GET()
        return result[0][0]
    def test_empty_token_renders_and_keeps_logout(self):
        result=self.render("<script>const TOKEN='';</script></body>")
        self.assertEqual(result[0],200);self.assertIn('/logout',result[1])
    def test_legacy_token_is_removed(self):
        result=self.render("const TOKEN='legacy-token';</body>")
        self.assertEqual(result[0],200);self.assertNotIn('legacy-token',result[1])
    def test_missing_duplicate_and_leaked_key_rejected(self):
        for source in ['</body>',"TOKEN='';TOKEN='';", "TOKEN='';"+gateway.KEY]:
            self.assertEqual(self.render(source)[0],500)
    def test_unauthenticated_source_denied(self):
        self.assertEqual(self.render('',False,'/index.html')[0],401)
    def test_sessions_unchanged(self):
        self.assertTrue(gateway.valid('moa_session='+gateway.session()))
        self.assertFalse(gateway.valid('moa_session=invalid'))
    def test_both_current_pages_have_empty_token(self):
        for p in [ROOT/'moa-site/dist/index.html',ROOT/'server-baseline/dashboard/dist/index.html']:
            self.assertEqual(self.render(p.read_text())[0],200)
if __name__=='__main__': unittest.main()
