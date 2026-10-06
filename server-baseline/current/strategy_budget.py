"""Atomic multi-strategy schema, allocations and account-wide ownership reservations."""
import datetime as dt
from contextlib import closing
import json
import os
import sqlite3
from decimal import Decimal
from pathlib import Path
from signal_validation import STRATEGIES, initial

PENDING = ('accepted', 'partial', 'unknown', 'reconcile_error')


def migrate(db):
    columns = db.execute('PRAGMA table_info(portfolios)').fetchall()
    legacy = columns and [x[1] for x in columns if x[5]] == ['market']
    db.execute('CREATE TABLE IF NOT EXISTS market_budgets (market TEXT PRIMARY KEY, total_cap TEXT NOT NULL, currency TEXT NOT NULL, mode TEXT NOT NULL DEFAULT "allocations", revision INTEGER NOT NULL DEFAULT 0)')
    if legacy:
        db.execute('ALTER TABLE portfolios RENAME TO portfolios_legacy_v1')
    db.execute('CREATE TABLE IF NOT EXISTS portfolios (market TEXT, strategy TEXT, enabled INTEGER, revision INTEGER, budget TEXT, started TEXT, data TEXT, PRIMARY KEY(market,strategy))')
    if legacy:
        db.execute('INSERT INTO portfolios SELECT * FROM portfolios_legacy_v1')
        db.execute("INSERT OR IGNORE INTO market_budgets(market,total_cap,currency) SELECT market,budget,CASE market WHEN 'KR' THEN 'KRW' ELSE 'USD' END FROM portfolios_legacy_v1")
    for market, default in [('KR', '500000'), ('US', '1000')]:
        db.execute('INSERT OR IGNORE INTO market_budgets(market,total_cap,currency) VALUES(?,?,?)', (market, default, 'KRW' if market == 'KR' else 'USD'))
        has_rows = db.execute('SELECT count(*) FROM portfolios WHERE market=?', (market,)).fetchone()[0]
        for strategy in STRATEGIES:
            db.execute('INSERT OR IGNORE INTO portfolios VALUES(?,?,0,0,?,NULL,?)',
                       (market, strategy, default if not has_rows and strategy == 'trend' else '0', json.dumps(initial(dt.datetime.now(dt.timezone.utc)))))
    intent_columns=[c[1] for c in db.execute('PRAGMA table_info(intents)')]
    if intent_columns and 'remaining' not in intent_columns:
        db.execute('ALTER TABLE intents ADD COLUMN remaining INTEGER')


def exposure(db, market, strategy=None):
    rows = db.execute('SELECT strategy,data FROM portfolios WHERE market=?' + (' AND strategy=?' if strategy else ''),
                      (market, strategy) if strategy else (market,)).fetchall()
    positions = {}
    used = Decimal(0)
    for row in rows:
        for key, p in json.loads(row['data'])['positions'].items():
            if key in positions:
                raise ValueError('duplicate_strategy_ownership')
            positions[key] = p
            used += Decimal(str(p['entry_price'])) * Decimal(str(p['quantity']))
    sql = "SELECT strategy,payload,applied,remaining FROM intents WHERE market=? AND status IN ('accepted','partial','unknown','reconcile_error')"
    params = (market,)
    if strategy:
        sql += ' AND strategy=?';params += (strategy,)
    buys = []
    for row in db.execute(sql, params):
        p = json.loads(row['payload'])
        if p['side'] == 'buy':
            remaining = max(0, int(p['quantity']) - row['applied']) if row['remaining'] is None else row['remaining']
            if not 0 <= remaining <= int(p['quantity'])-row['applied']:
                raise ValueError('invalid_order_reservation')
            used += Decimal(str(p['price'])) * remaining * Decimal('1.01')
            buys.append(p)
    slots = set(positions) | {p['exchange']+':'+p['code'] for p in buys}
    return used, slots


def allocate(db, market, strategy, amount):
    if not isinstance(amount, str) or not amount.isascii() or not amount.isdecimal() or len(amount)>9 or not 0 <= int(amount) <= (100000000 if market == 'KR' else 100000):
        raise ValueError('invalid_auto_budget')
    row = db.execute('SELECT * FROM portfolios WHERE market=? AND strategy=?', (market, strategy)).fetchone()
    used, _ = exposure(db, market, strategy)
    if Decimal(amount) < used or (row['enabled'] and int(amount) == 0):
        raise ValueError('allocation_below_committed')
    cap = db.execute('SELECT * FROM market_budgets WHERE market=?', (market,)).fetchone()
    total = sum(Decimal(x[0]) for x in db.execute('SELECT budget FROM portfolios WHERE market=? AND strategy<>?', (market, strategy))) + Decimal(amount)
    if total > Decimal(cap['total_cap']):
        raise ValueError('market_allocation_cap')
    db.execute('UPDATE portfolios SET budget=?,revision=revision+1 WHERE market=? AND strategy=?', (amount, market, strategy))
    db.execute('UPDATE market_budgets SET revision=revision+1 WHERE market=?', (market,))
    return amount


def overview(db, market):
    cap = dict(db.execute('SELECT * FROM market_budgets WHERE market=?', (market,)).fetchone())
    rows = []
    for row in db.execute('SELECT * FROM portfolios WHERE market=? ORDER BY strategy', (market,)):
        used, slots = exposure(db, market, row['strategy'])
        rows.append(dict(strategy=row['strategy'], enabled=bool(row['enabled']), allocation=row['budget'],
                         committed=str(used), slots=len(slots), positions=len(json.loads(row['data'])['positions'])))
    return dict(**cap, allocated=str(sum(Decimal(x['allocation']) for x in rows)), strategies=rows)


def migrate_file(path, backup):
    """Offline caller must stop writers; backup includes every table and ledger."""
    path, backup = Path(path).absolute(), Path(backup).absolute()
    if not path.is_file() or path.is_symlink() or backup.is_symlink():
        raise ValueError('invalid_database_path')
    try:
        os.close(os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600))
    except FileExistsError:
        raise ValueError('backup_exists') from None
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(backup)) as dst:
        src.backup(dst)
    db = sqlite3.connect(path)
    try:
        db.row_factory = sqlite3.Row
        with db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
    finally:
        db.close()


def restore_file(path, backup):
    """Offline rollback restores exact pre-migration DB; never call with live writers."""
    import shutil, tempfile
    path,backup = Path(path),Path(backup)
    if not path.is_file() or path.is_symlink() or not backup.is_file() or backup.is_symlink():
        raise ValueError('invalid_database_path')
    if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ValueError('rollback_requires_offline_clean_database')
    previous=path.stat()
    fd, temporary = tempfile.mkstemp(prefix='.strategy-rollback-', dir=path.parent)
    os.close(fd)
    try:
        shutil.copy2(backup, temporary)
        with sqlite3.connect('file:'+temporary+'?mode=ro', uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('invalid_backup')
        os.chmod(temporary,previous.st_mode & 0o777)
        if (os.stat(temporary).st_uid,os.stat(temporary).st_gid)!=(previous.st_uid,previous.st_gid):
            os.chown(temporary,previous.st_uid,previous.st_gid)
        with open(temporary,'rb') as handle:os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Offline migration/rollback only; all DB writers must be stopped first.')
    parser.add_argument('action',choices=('migrate','rollback'))
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--writers-stopped',action='store_true',required=True)
    args=parser.parse_args()
    if not args.database.is_file():
        parser.error('database must exist')
    if args.action=='migrate':
        migrate_file(args.database,args.backup)
    else:
        restore_file(args.database,args.backup)
    print('OFFLINE_'+args.action.upper()+'_OK')

if __name__=='__main__':
    main()
