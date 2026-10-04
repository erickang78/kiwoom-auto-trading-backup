"""Broker-verified restart checks. Never submit, cancel, or replace an order here."""
import datetime as dt
import json
import re

REASONS={
 'unknown_order':'주문 접수 응답 또는 주문번호를 확인하지 못했습니다.',
 'unverified_order':'증권사 주문 내역에서 기존 주문을 확인하지 못했습니다.',
 'ownership_mismatch':'자동매매 보유 수량과 실전 계좌 보유 수량이 다릅니다.',
 'order_quantity_mismatch':'주문 수량과 체결·미체결 수량이 맞지 않습니다.',
 'order_stock_mismatch':'주문 내역의 종목이 자동매매 기록과 다릅니다.',
 'unowned_sale':'자동매매로 확인되지 않은 보유분의 매도 체결이 발견됐습니다.',
 'duplicate_fill':'체결 내역과 기존 보유 기록을 함께 확인해야 합니다.',
}
STAGES={'submit':'주문 전송','reconcile':'주문·체결 확인','account':'계좌·보유 수량 확인','proposal':'주문 조건 점검'}

def explanation(db,row,state):
    unresolved=[dict(x) for x in db.execute("SELECT id,payload,number,created FROM intents WHERE market=? AND status IN ('unknown','reconcile_error') ORDER BY id",(row['market'],))]
    failure=state.get('last_failure') or {}
    reason=REASONS.get(failure.get('reason'))
    if not reason and unresolved:reason=REASONS['unknown_order']
    if not reason and state.get('status')=='attention':reason='계좌 또는 주문 조회 결과를 검증하지 못해 중지했습니다.'
    if not reason:reason='사용자가 실제매매를 중지했습니다.' if row['started'] and not row['enabled'] else '실제매매를 아직 시작하지 않았습니다.'
    result=dict(reason=reason,stage=STAGES.get(failure.get('stage'),''),at=state.get('last_check'),orders=[])
    for item in unresolved:
        p=json.loads(item['payload']); f=db.execute('SELECT data FROM intent_failures WHERE intent_id=?',(item['id'],)).fetchone()
        item=dict(id=item['id'],name=p.get('name',p['code']),code=p['code'],side=p['side'],quantity=p['quantity'],price=p['price'],number=item['number'],created=item['created'])
        if f:item['failure']=json.loads(f[0])
        result['orders'].append(item)
    return result

def check(db,row,state,body,now=None):
    import auto_trading as a
    now=now or dt.datetime.now(dt.timezone.utc)
    summary=dict(result='blocked',checked_at=a.stamp(now),message='',orders=[],recovered=[])
    db.execute('SAVEPOINT restart_check')
    try:
        c=a.trade.client('real') # Refresh authentication; all following broker calls are read-only.
        holdings,sellable,reserved=a.account(c,row['market'])
        unresolved=db.execute("SELECT * FROM intents WHERE market=? AND status IN ('unknown','reconcile_error') ORDER BY id",(row['market'],)).fetchall()
        confirmed=body.get('confirmed_absent_orders',[])
        if not isinstance(confirmed,list) or any(type(x) is not int for x in confirmed):raise ValueError('invalid_recovery_confirmation')
        cache={}
        for intent in unresolved:
            if intent['number']:continue # Existing order numbers are reconciled below.
            p=json.loads(intent['payload']);created=dt.datetime.fromisoformat(intent['created']).astimezone(dt.timezone(dt.timedelta(hours=9)))
            day=created.strftime('%Y%m%d')
            if day not in cache:cache[day]=a.order_rows(c,row['market'],day)
            # Any order in this stock at/after the send could be relevant. Never guess identity.
            relevant=[];valid_times=row['market']=='KR'
            for report in cache[day]:
                if a.stock_code(report.get('stk_cd',''),row['market'])!=p['code']:continue
                raw=str(report.get('ord_tm','')).replace(':','')
                if not re.fullmatch(r'\d{6}',raw):valid_times=False;relevant.append(report);continue
                if raw>=created.strftime('%H%M%S'):relevant.append(report)
            owned={x['code']:x['quantity'] for x in state['positions'].values()}
            consistent=all(holdings.get(code,0)==qty for code,qty in owned.items())
            absent=(valid_times and not relevant and consistent and p['code'] not in reserved
                    and holdings.get(p['code'],0)==owned.get(p['code'],0)
                    and not intent['filled'] and not intent['applied'])
            item=dict(id=intent['id'],code=p['code'],name=p.get('name',p['code']),side=p['side'],quantity=p['quantity'],price=p['price'],created=intent['created'],can_confirm_absent=absent,
                      message='증권사 주문 내역에 해당 시점 이후 주문이 없고, 보유·미체결 수량이 일치합니다. 키움에서도 미접수임을 확인해 주세요.' if absent else '주문 접수 여부가 불명확합니다. 키움 주문 내역을 확인해야 합니다.')
            if row['market']=='KR':
                item['price_issue']=a.kr_price_issue(p['code'],a.number(p['price']),now,c)
            summary['orders'].append(item)
            if intent['id'] in confirmed and body.get('confirmed') is True and absent:
                diagnostic=dict(stage='restart',kind='not_submitted_confirmed',message='계좌·주문 조회와 사용자 미접수 확인으로 정리',at=a.stamp(now))
                db.execute("UPDATE intents SET status='failed',dedup=dedup||?,updated=? WHERE id=?",(':confirmed-no-order:'+str(intent['id']),a.stamp(now),intent['id']))
                db.execute('INSERT OR REPLACE INTO intent_failures VALUES (?,?)',(intent['id'],json.dumps(diagnostic)))
                if p['side']=='buy':
                    for key in list(state['seen']):
                        if key.endswith(':'+p['exchange']+':'+p['code']):state['seen'].pop(key,None)
                summary['recovered'].append(intent['id'])
        remaining=db.execute("SELECT COUNT(*) FROM intents WHERE market=? AND status IN ('unknown','reconcile_error') AND (number IS NULL OR number='')",(row['market'],)).fetchone()[0]
        if remaining:
            raise RuntimeError('unknown_order')
        a.reconcile(db,c,row,state,now)
        for p in state['positions'].values():
            if holdings.get(p['code'],0)!=p['quantity']:raise RuntimeError('ownership_mismatch')
        summary.update(result='ready',message='인증·계좌·기존 주문 점검을 완료했습니다. 재시작할 수 있습니다.')
        db.execute('RELEASE restart_check')
    except Exception as error:
        db.execute('ROLLBACK TO restart_check');db.execute('RELEASE restart_check')
        summary['recovered']=[]
        summary['message']=REASONS.get(str(error),'증권사 계좌·주문 조회에 실패했습니다. 연결을 확인하고 다시 점검해 주세요.')
        summary['error_type']=type(error).__name__
    state['restart_check']=summary
    return summary
