import json,sqlite3,tempfile,time,unittest
from pathlib import Path
import kakao_notifications as k
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'secret.sqlite';self.trades=Path(self.tmp.name)/'trades.sqlite';self.calls=[]
  with sqlite3.connect(self.trades) as d:d.execute('CREATE TABLE intents(id INTEGER PRIMARY KEY,market,strategy,payload,applied,filled,average,updated)')
 def fill(self,id,qty=1,side='buy',market='KR',reason=''):
  with sqlite3.connect(self.trades) as d:d.execute('INSERT OR REPLACE INTO intents VALUES(?,?,?,?,?,?,?,?)',(id,market,'breakout',json.dumps(dict(side=side,name='샘플',code='A',quantity=2,reason=reason)),qty,qty,'12345','2026-10-01T00:00:00+00:00'))
 def call(self,url,form=None,token=None):
  self.calls.append((url,form,token))
  return dict(access_token='ACCESS',refresh_token='REFRESH',expires_in=21600,refresh_token_expires_in=5000000,scope='talk_message') if url.endswith('/token') else dict(result_code=0)
 def control(self,action,**kw):return k.control(dict(action=action,**kw),self.path,self.trades,self.call)
 def connect(self):
  self.control('setup',client_id='a'*32);self.control('authorize')
  with k.locked(self.path) as db:state=k.load(db)['state']
  return self.control('exchange',code='CODE',state=state)
 def test_state_single_use_and_no_secrets(self):
  self.control('setup',client_id='a'*32);self.control('authorize')
  with self.assertRaises(k.KakaoError):self.control('exchange',state='bad',code='CODE')
  r=self.connect();self.assertTrue(r['connected']);self.assertNotIn('ACCESS',json.dumps(r));self.assertNotIn('REFRESH',json.dumps(r));self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
  with self.assertRaises(k.KakaoError):self.control('exchange',state='old',code='CODE')
 def test_baseline_delta_dedup_and_disconnect(self):
  self.fill(1);self.connect();k.cycle(self.path,self.trades,self.call);self.assertEqual(len(self.calls),1)
  self.fill(1,2);k.cycle(self.path,self.trades,self.call);k.cycle(self.path,self.trades,self.call);self.assertEqual(len(self.calls),2)
  text=json.loads(self.calls[-1][1]['template_object'])['text'];self.assertIn('이번 체결 1주',text);self.assertIn('누적 2주',text)
  self.fill(2,1,'sell','US');k.cycle(self.path,self.trades,self.call);self.assertIn('[실제매매] 매도 체결내역',json.loads(self.calls[-1][1]['template_object'])['text'])
  self.control('disconnect');self.fill(3);k.cycle(self.path,self.trades,self.call);self.assertEqual(len(self.calls),3)
 def test_real_sell_reason(self):
  self.connect()
  for id,reason in [(1,'익절 +5%'),(2,'손절 -3%'),(3,'')]:
   self.fill(id,1,'sell','KR',reason);k.cycle(self.path,self.trades,self.call)
   text=json.loads(self.calls[-1][1]['template_object'])['text']
   self.assertIn('매도 사유: '+(reason or '사유 기록 없음'),text)
   self.assertIn('[실제매매] '+('익절 매도' if reason.startswith('익절') else '손절 매도' if reason.startswith('손절') else '매도')+' 체결내역',text)
  self.fill(4,1,'buy','KR','매수 조건');k.cycle(self.path,self.trades,self.call)
  self.assertNotIn('매도 사유:',json.loads(self.calls[-1][1]['template_object'])['text'])
 def test_refresh_rotation_preserved(self):
  self.connect()
  with k.locked(self.path) as db:
   c=k.load(db);c['expires_at']=0;k.save(db,c)
   k.token(db,c,self.call);self.assertEqual(k.load(db)['refresh_token'],'REFRESH');self.assertGreater(k.load(db)['expires_at'],time.time())
 def test_ambiguous_delivery_not_repeated(self):
  self.connect();self.fill(1)
  def fail(url,form=None,token=None):raise k.KakaoError('kakao_delivery_unconfirmed')
  k.cycle(self.path,self.trades,fail);k.cycle(self.path,self.trades,self.call)
  r=self.control('status');self.assertEqual(r['uncertain'],1);self.assertEqual(len(self.calls),1)
 def test_virtual_baseline_and_market_side_and_dedup(self):
  signals=Path(self.tmp.name)/'signals.sqlite'
  with sqlite3.connect(signals) as d:
   d.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,data,portfolio)')
   def event(kind):return json.dumps(dict(kind=kind,strategy='trend',name='샘플',code='A',quantity=2,reference_price=10000,reason='조건 충족',at='2026-10-01T00:00:00+00:00',return_pct=5))
   d.execute('INSERT INTO events VALUES(1,?,6)',(event('BUY'),))
  self.connect()
  with k.locked(self.path) as d:d.execute('DROP TABLE virtual_cursor');d.commit()
  k.cycle(self.path,self.trades,self.call,signals=signals)
  self.assertEqual(len(self.calls),1)
  with sqlite3.connect(signals) as d:
   d.execute('INSERT INTO events VALUES(2,?,6)',(event('BUY'),));d.execute('INSERT INTO events VALUES(3,?,1)',(event('SELL'),))
  k.cycle(self.path,self.trades,self.call,signals=signals);k.cycle(self.path,self.trades,self.call,signals=signals);k.cycle(self.path,self.trades,self.call,signals=signals)
  self.assertEqual(len(self.calls),3)
  texts=[json.loads(c[1]['template_object'])['text'] for c in self.calls[1:]]
  self.assertIn('[가상매매] 매수 체결내역',texts[0]);self.assertIn('국내',texts[0]);self.assertIn('10,000원',texts[0])
  self.assertIn('[가상매매] 매도 체결내역',texts[1]);self.assertIn('미국',texts[1]);self.assertIn('+5.00%',texts[1])
 def test_missing_permission(self):
  self.control('setup',client_id='a'*32);self.control('authorize')
  with k.locked(self.path) as db:state=k.load(db)['state']
  def no_scope(*args):return dict(access_token='a',refresh_token='r',expires_in=10,scope='profile')
  with self.assertRaises(k.KakaoError):k.control(dict(action='exchange',state=state,code='c'),self.path,self.trades,no_scope)
  self.assertFalse(self.control('status')['connected'])
if __name__=='__main__':unittest.main()
