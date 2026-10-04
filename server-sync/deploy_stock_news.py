"""Run on AWS with /tmp/stock-news-payload.json. Preserve unrelated edits."""
import datetime
import json
from pathlib import Path
import shutil


def patch_api(source):
    if 'from news_api import stock_news' in source:
        raise ValueError('news_already_installed')
    replacements = [
        ('        is_price = ', "        is_news = self.path == '/v1/market/news'\n        is_price = is_news or "),
        ('            if is_quote_domestic:\n', "            if is_news:\n                from news_api import stock_news\n                return self._json(200, stock_news(str(body.get('market', '')), str(body.get('code', '')), str(body.get('name', ''))))\n            if is_quote_domestic:\n"),
    ]
    for old,new in replacements:
        assert source.count(old)==1, old
        source=source.replace(old,new)
    compile(source,'refresh_api.py','exec')
    return source


def patch_html(source, ui):
    assert '<script id="stock-news-module">' not in source
    assert source.count('</body>')==1
    return source.replace('</body>','<script id="stock-news-module">\n'+ui+'\n</script></body>')


if __name__=='__main__':
    payload=json.loads(Path('/tmp/stock-news-payload.json').read_text())
    root=Path('/opt/kiwoom/current')
    api=root/'refresh_api.py'
    html=Path('/opt/kiwoom/dashboard-source/dist/index.html')
    news=root/'news_api.py'
    changes=[(api,patch_api(api.read_text())),(html,patch_html(html.read_text(),payload['ui'])),(news,payload['api'])]
    for path,content in changes:
        if path.suffix=='.py': compile(content,str(path),'exec')
    suffix='.before-stock-news-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    for path,content in changes:
        if path.exists(): shutil.copy2(path,path.with_name(path.name+suffix))
    for path,content in changes:
        tmp=path.with_name(path.name+'.news-new');tmp.write_text(content);tmp.replace(path)
    print('STOCK_NEWS_DEPLOYED',suffix)
