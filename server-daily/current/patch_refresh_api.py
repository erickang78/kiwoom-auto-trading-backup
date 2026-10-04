from pathlib import Path
import shutil
p=Path("refresh_api.py"); s=p.read_text(); backup=p.with_suffix(".py.before-upbit")
if not backup.exists(): shutil.copy2(p,backup)
s=s.replace("from credentials import load_credentials\n","from credentials import load_credentials\nfrom upbit_read import snapshot as upbit_snapshot, UpbitNotConfigured\n")
s=s.replace("GOLD_CREDENTIALS = Path('/opt/kiwoom/secrets/gold-credentials.json')\n","GOLD_CREDENTIALS = Path('/opt/kiwoom/secrets/gold-credentials.json')\nUPBIT_CREDENTIALS = Path('/opt/kiwoom/secrets/upbit-credentials.json')\n")
s=s.replace("        is_flow = self.path == '/v1/market/investor-flow'\n        if not mode and not is_flow:\n","        is_flow = self.path == '/v1/market/investor-flow'\n        is_coin = self.path == '/v1/coin/refresh'\n        if not mode and not is_flow and not is_coin:\n")
s=s.replace("                return self._json(200, investor_flow(str(body.get('code',''))) if is_flow else public_snapshot(mode))\n            except ValueError: return self._json(400, {'error':'invalid_stock_code'})\n            except Exception:\n                return self._json(502, {'error': 'broker_refresh_failed'})\n","                if is_coin:\n                    return self._json(200, upbit_snapshot(UPBIT_CREDENTIALS))\n                return self._json(200, investor_flow(str(body.get('code',''))) if is_flow else public_snapshot(mode))\n            except UpbitNotConfigured:\n                return self._json(503, {'error': 'upbit_not_configured'})\n            except ValueError: return self._json(400, {'error':'invalid_stock_code'})\n            except Exception:\n                return self._json(502, {'error': 'upbit_refresh_failed' if is_coin else 'broker_refresh_failed'})\n")
compile(s,str(p),"exec")
if "'/v1/coin/refresh'" not in s or "upbit_snapshot(UPBIT_CREDENTIALS)" not in s: raise SystemExit("upbit route patch failed")
p.write_text(s); print("UPBIT_ROUTE_UPDATED")
