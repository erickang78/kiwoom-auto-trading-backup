"""Persistent cross-process gate shared by paper fills and broker submissions."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

DB = Path('/opt/kiwoom/state/trading-control.sqlite3')

@contextmanager
def locked(path=DB):
    db = sqlite3.connect(path, timeout=120)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, revision INTEGER NOT NULL)')
        db.execute('INSERT OR IGNORE INTO control VALUES (1,1,0)')
        db.commit()
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()

def read(db):
    enabled, revision = db.execute('SELECT enabled,revision FROM control WHERE id=1').fetchone()
    return {'enabled': bool(enabled), 'revision': revision}

def status(action='status', path=DB, signal_path=None):
    if action not in ('status', 'pause', 'resume'):
        raise ValueError('invalid_trading_action')
    with locked(path) as db:
        if action != 'status':
            if action == 'resume':
                from signal_validation import connect, DB as SIGNAL_DB
                with connect(signal_path or SIGNAL_DB) as signals:
                    signals.execute('UPDATE state SET enabled=1, revision=revision+1')
            db.execute('UPDATE control SET enabled=?,revision=revision+1 WHERE id=1', (action == 'resume',))
        return read(db)

@contextmanager
def permit(path=DB):
    # Hold the gate through submission: stop acknowledgement cannot race an order.
    with locked(path) as db:
        if not read(db)['enabled']:
            raise ValueError('trading_paused')
        yield
