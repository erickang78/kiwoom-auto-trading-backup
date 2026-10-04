"""Read-only domestic Kiwoom MOCK snapshot. Credentials stay in memory."""
import argparse
import datetime
import getpass
import json
import re
import time
import urllib.error
import urllib.request

from credentials import DEFAULT_PATH, REAL_PATH, load_credentials

BASE = 'https://mockapi.kiwoom.com'
REAL_BASE = 'https://api.kiwoom.com'
PATHS = {'ka10001': '/api/dostk/stkinfo', 'kt00001': '/api/dostk/acnt',
         'kt00018': '/api/dostk/acnt', 'kt50020': '/api/dostk/acnt',
         'kt50030': '/api/dostk/acnt', 'kt50075': '/api/dostk/acnt', 'ka10059': '/api/dostk/stkinfo'}


class BrokerError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BrokerError('Unexpected redirect blocked')


class Client:
    def __init__(self, base=BASE):
        if base not in (BASE, REAL_BASE):
            raise BrokerError('Unsupported broker environment')
        self.base = base
        self.token = None
        self.open = urllib.request.build_opener(NoRedirect()).open

    def _post(self, path, body, headers):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json;charset=UTF-8', **headers})
        try:
            with self.open(req, timeout=20) as response:
                data = json.load(response)
                continuation = (response.headers.get('cont-yn', 'N'), response.headers.get('next-key', ''))
        except urllib.error.HTTPError as exc:
            raise BrokerError('Kiwoom HTTP error api_id=%s status=%s body=%s' % (headers.get('api-id',''), exc.code, exc.read().decode('utf-8','replace'))) from None
        except (OSError, ValueError):
            raise BrokerError('Connection or invalid JSON response') from None
        if not isinstance(data, dict) or str(data.get('return_code')) != '0':
            # Never echo broker messages: they may contain sensitive values.
            raise BrokerError("Kiwoom API error api_id=%s return_code=%s return_msg=%s raw=%s" % (headers.get("api-id",""), data.get("return_code"), data.get("return_msg",""), json.dumps(data, ensure_ascii=True)))
        return data, continuation

    def authenticate(self, key, secret):
        if not key or not secret:
            raise BrokerError('Empty credentials')
        data, _ = self._post('/oauth2/token', {'grant_type': 'client_credentials',
                            'appkey': key, 'secretkey': secret}, {})
        if not isinstance(data.get('token'), str) or not data['token']:
            raise BrokerError('Missing token')
        self.token = data['token']

    def pages(self, api, body):
        if api not in PATHS or not self.token:
            raise BrokerError('Read-only API allowlist or authentication check failed')
        key, seen = '', set()
        for _ in range(100):
            time.sleep(.3)
            data, (more, next_key) = self._post(PATHS[api], body, {
                'api-id': api, 'authorization': 'Bearer ' + self.token,
                'cont-yn': 'Y' if key else 'N', 'next-key': key})
            yield data
            if more != 'Y':
                return
            if not next_key or next_key in seen:
                raise BrokerError('Invalid pagination; snapshot incomplete')
            seen.add(next_key)
            key = next_key
        raise BrokerError('Page limit reached; snapshot incomplete')


def pick(data, fields):
    return {name: data.get(name) for name in fields.split()}


def snapshot(client, code):
    if not re.fullmatch(r'[0-9A-Z]{6}', code):
        raise BrokerError('Use a six-character KRX stock code')
    quote = list(client.pages('ka10001', {'stk_cd': code}))[0]
    cash = list(client.pages('kt00001', {'qry_tp': '3'}))[0]
    balances = list(client.pages('kt00018', {'qry_tp': '2', 'dmst_stex_tp': 'KRX'}))
    holdings = []
    for page in balances:
        rows = page.get('acnt_evlt_remn_indv_tot')
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise BrokerError('Unexpected holdings schema; snapshot incomplete')
        holdings.extend(pick(row, 'stk_cd stk_nm rmnd_qty trde_able_qty cur_prc pur_pric evlt_amt evltv_prft') for row in rows)
    environment = 'REAL' if client.base == REAL_BASE else 'MOCK'
    return {'mode': environment + '_READ_ONLY', 'source': client.base, 'orders_enabled': False,
            'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'note': 'Broker quote, freshness not guaranteed; numeric strings kept as supplied. Not an atomic snapshot.',
            'quote': pick(quote, 'stk_cd stk_nm cur_prc base_pric flu_rt trde_qty'),
            'cash': pick(cash, 'entr ord_alow_amt d1_entra d2_entra'),
            'balance': pick(balances[0], 'tot_pur_amt tot_evlt_amt tot_evlt_pl prsm_dpst_aset_amt'),
            'holdings': holdings, 'balance_pages': len(balances)}


def gold_snapshot(client):
    """Return the linked KRX gold spot account balance without placing orders."""
    pages = list(client.pages('kt50020', {}))
    positions = []
    for page in pages:
        rows = page.get('gold_acnt_evlt_prst')
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise BrokerError('Unexpected gold balance schema; snapshot incomplete')
        positions.extend(pick(row, (
            'stk_cd stk_nm real_qty avg_prc cur_prc est_amt est_lspft est_ratio '
            'book_amt2 pl_prch_prc qty able_qty'
        )) for row in rows)
    summary = pick(pages[0], (
        'tot_entr net_entr tot_est_amt net_amt tot_book_amt2 tot_dep_amt '
        'paym_alowa pl_amt'
    ))
    return {'connected': True, 'summary': summary, 'positions': positions}


def main():
    parser = argparse.ArgumentParser(description='Domestic quote and balance; read-only, no orders')
    parser.add_argument('--code', default='005930', help='KRX code; default is a connection test, not a recommendation')
    parser.add_argument('--environment', choices=('mock', 'real'), default='mock')
    args = parser.parse_args()
    try:
        real = args.environment == 'real'
        client = Client(REAL_BASE if real else BASE)
        client.authenticate(*load_credentials(REAL_PATH if real else DEFAULT_PATH))
        result = snapshot(client, args.code)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        print('READ_ONLY_OK - no orders sent')
    except (BrokerError, KeyboardInterrupt) as exc:
        parser.exit(1, 'READ_ONLY_FAILED: ' + (str(exc) or 'cancelled') + '\n')


if __name__ == '__main__':
    main()
