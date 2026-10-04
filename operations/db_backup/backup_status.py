"""Only sanitized backup health is exposed to authenticated dashboard sessions."""
import datetime as dt
import json
from pathlib import Path

def read_status(path='/opt/kiwoom/backup-status/status.json',now=None,kind='database'):
    now=now or dt.datetime.now(dt.timezone.utc)
    result={'status':'unavailable','last_success':None,'last_attempt':None,'database_count':None,'stale_after_seconds':93600}
    try:
        data=json.loads(Path(path).read_text())
        for field in ('last_success','last_attempt'):
            if data.get(field):
                timestamp=dt.datetime.fromisoformat(data[field])
                if timestamp.tzinfo is None or timestamp>now+dt.timedelta(minutes=5):raise ValueError('invalid_time')
                result[field]=timestamp.isoformat()
        complete=data.get('database_count')==5 if kind=='database' else isinstance(data.get('file_count'),int) and data['file_count']>0
        if data.get('database_count')==5:result['database_count']=5
        if data.get('ok') is False:result['status']='failed'
        elif not result['last_success']:result['status']='never'
        else:
            age=(now-dt.datetime.fromisoformat(result['last_success'])).total_seconds()
            result['status']='stale' if age>=93600 else ('ok' if data.get('ok') is True and complete else 'unavailable')
        if kind=='database':result['code']=read_status(Path(path).with_name('code-status.json'),now,kind='code')
        return result
    except FileNotFoundError:result['status']='never'
    except (OSError,ValueError,TypeError,AttributeError):pass
    return result
