from pathlib import Path
import datetime, shutil, sqlite3, subprocess

def deploy(test_source):
    root=Path('/opt/kiwoom/current');engine=root/'auto_trading.py';notice=root/'kakao_notifications.py'
    e=engine.read_text();n=notice.read_text()
    old="                        order['name'] = event['name']"
    new=old+"\n                        order['reason'] = str(event.get('reason') or '')"
    assert e.count(old)==1 and new not in e
    e=e.replace(old,new)
    old_notice='        db.execute("INSERT OR IGNORE INTO queue(intent,qty,text,status)'
    assert old_notice in n and "매도 사유:" not in n
    n=n.replace(old_notice,"        if side=='sell':text+='\\n매도 사유: '+str(p.get('reason') or '사유 기록 없음')\n"+old_notice,1)
    compile(e,'auto_trading.py','exec');compile(n,'kakao_notifications.py','exec')
    def settings():
        with sqlite3.connect('file:/opt/kiwoom/state/auto-trading.sqlite3?mode=ro',uri=True) as db:
            return db.execute('SELECT market,strategy,enabled,revision,budget,started FROM portfolios ORDER BY market').fetchall()
    before=settings();suffix='.before-kakao-sell-reason-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    shutil.copy2(engine,str(engine)+suffix);shutil.copy2(notice,str(notice)+suffix)
    subprocess.run(['systemctl','stop','moa-kakao-notifications'],check=True)
    try:
        engine.write_text(e);notice.write_text(n);(root/'test_kakao_notifications.py').write_text(test_source)
        subprocess.run(['python3','-m','unittest','test_kakao_notifications'],cwd=root,check=True)
        subprocess.run(['systemctl','restart','moa-auto-trading'],check=True)
        assert settings()==before,'Execution settings changed'
    except BaseException:
        shutil.copy2(str(engine)+suffix,engine);shutil.copy2(str(notice)+suffix,notice)
        subprocess.run(['systemctl','restart','moa-auto-trading'],check=True)
        raise
    finally:
        subprocess.run(['systemctl','start','moa-kakao-notifications'],check=True)
    subprocess.run(['systemctl','is-active','moa-auto-trading','moa-kakao-notifications','kiwoom-refresh'],check=True)
    print('KAKAO_SELL_REASON_UPDATED',suffix,'SETTINGS_UNCHANGED')
