"""Production Kiwoom connection check limited to quote, cash, and holdings."""
import argparse
import json
from pathlib import Path

import broker_read as broker
from credentials import load_credentials


REAL_BASE = 'https://api.kiwoom.com'
REAL_CREDENTIALS = Path('/opt/kiwoom/secrets/real-credentials.json')


def main():
    parser = argparse.ArgumentParser(description='REAL account read-only connection check')
    parser.add_argument('--code', default='005930')
    args = parser.parse_args()
    broker.BASE = REAL_BASE
    client = broker.Client()
    client.authenticate(*load_credentials(REAL_CREDENTIALS))
    result = broker.snapshot(client, args.code)
    result.update(mode='REAL_READ_ONLY', source=REAL_BASE, orders_enabled=False)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    print('REAL_READ_ONLY_OK - no orders sent')


if __name__ == '__main__':
    try:
        main()
    except (broker.BrokerError, KeyboardInterrupt) as exc:
        raise SystemExit('REAL_READ_ONLY_FAILED: ' + (str(exc) or 'cancelled'))
