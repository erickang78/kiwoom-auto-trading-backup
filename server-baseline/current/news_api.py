"""Read-only Google News RSS search. No brokerage credentials are sent."""
import datetime as dt
import re
import threading
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

_CACHE = {}
_LOCK = threading.Lock()
_MAX_BYTES = 2_000_000


def parse_feed(raw, terms=()):
    root = ET.fromstring(raw)
    if root.tag != 'rss':
        raise ValueError('invalid_news_feed')
    rows = []
    seen = set()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    for item in root.findall('./channel/item'):
        title = (item.findtext('title') or '').strip()
        source = (item.findtext('source') or '').strip()
        url = (item.findtext('link') or '').strip()
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname != 'news.google.com' or parts.username or parts.port not in (None, 443):
            continue
        if not parts.path.startswith('/rss/articles/'):
            continue
        try:
            date = parsedate_to_datetime(item.findtext('pubDate') or '')
            if date.tzinfo is None:
                date = date.replace(tzinfo=dt.timezone.utc)
            date = date.astimezone(dt.timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
        if date < cutoff or date > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10):
            continue
        if source and title.endswith(' - ' + source):
            title = title[:-len(source)-3].strip()
        if terms and not any(re.search(r'(?<![a-z0-9])' + re.escape(term.casefold()) + r'(?![a-z0-9])', title.casefold()) for term in terms):
            continue
        key = re.sub(r'\s+', ' ', title).casefold()
        if not title or key in seen:
            continue
        seen.add(key)
        rows.append({'title': title[:500], 'source': source[:120], 'url': url,
                     'published_at': date.isoformat()})
    rows.sort(key=lambda row: row['published_at'], reverse=True)
    return rows[:5]


def stock_news(market, code, name):
    if market not in ('KR', 'US') or not isinstance(code, str) or not re.fullmatch(r'\d{6}' if market == 'KR' else r'[A-Z0-9.\-/]{1,12}', code):
        raise ValueError('invalid_stock_code')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError('invalid_stock_name')
    # Treat the company name as text, not Google search operators.
    name = re.sub(r'[^\w\s가-힣.&-]', ' ', name).strip()
    if not name:
        raise ValueError('invalid_stock_name')
    key = (market, code, name)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
    query = f'"{name}" 주식 when:7d' if market == 'KR' else f'"{name}" {code} stock when:7d'
    params = {'q': query, 'hl': 'ko' if market == 'KR' else 'en-US',
              'gl': 'KR' if market == 'KR' else 'US', 'ceid': 'KR:ko' if market == 'KR' else 'US:en'}
    request = Request('https://news.google.com/rss/search?' + urlencode(params),
                      headers={'User-Agent': 'MoaDashboard/1.0', 'Accept': 'application/rss+xml'})
    try:
        with urlopen(request, timeout=6) as response:
            raw = response.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ValueError('news_feed_too_large')
        company = re.sub(r'\s+(?:INC|CORP|CORPORATION|CO|LTD|LIMITED|PLC)\.?$', '', name, flags=re.I).strip()
        terms = [company or name] + ([code] if market == 'US' else [])
        result = {'status': 'ok', 'items': parse_feed(raw, terms)}
    except Exception:
        return {'status': 'unavailable', 'items': []}
    result.update(market=market, code=code, retrieved_at=dt.datetime.now(dt.timezone.utc).isoformat())
    with _LOCK:
        if len(_CACHE) >= 128:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (time.monotonic(), result)
    return result
