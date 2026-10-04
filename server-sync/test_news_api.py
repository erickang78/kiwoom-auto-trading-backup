import datetime as dt
import unittest
from email.utils import format_datetime
from unittest.mock import patch, MagicMock
import news_api as n


def item(title, age=0, url='https://news.google.com/rss/articles/abc'):
    date=format_datetime(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=age))
    return f'<item><title>{title} - Press</title><source>Press</source><link>{url}</link><pubDate>{date}</pubDate></item>'


def feed(items):
    return ('<rss><channel>'+''.join(items)+'</channel></rss>').encode()


class NewsTests(unittest.TestCase):
    def setUp(self): n._CACHE.clear()

    def test_filter_dedupe_sort_limit(self):
        data=feed([item('old',8),item('unsafe',url='javascript:alert(1)'),item('outside',url='https://evil.example/rss/articles/abc'),item('same'),item('same')]+[item(str(i),i/10) for i in range(8)])
        rows=n.parse_feed(data)
        self.assertEqual(len(rows),5)
        self.assertEqual(sum(r['title']=='same' for r in rows),1)
        self.assertNotIn('old',[r['title'] for r in rows])
        self.assertEqual(rows, sorted(rows,key=lambda r:r['published_at'],reverse=True))

    def test_title_must_match_company_or_ticker(self):
        rows=n.parse_feed(feed([item('unrelated spam'),item('Apple earnings'),item('AAPL rises'),item('pineapple harvest')]), ['Apple','AAPL'])
        self.assertEqual({r['title'] for r in rows},{'Apple earnings','AAPL rises'})

    @patch.object(n,'urlopen')
    def test_cache_and_fixed_origin(self,op):
        op.return_value.__enter__.return_value.read.return_value=feed([item('news')])
        self.assertEqual(n.stock_news('KR','005930','삼성전자')['status'],'ok')
        n.stock_news('KR','005930','삼성전자')
        self.assertEqual(op.call_count,1)
        self.assertTrue(op.call_args.args[0].full_url.startswith('https://news.google.com/rss/search?'))
        self.assertNotIn('Authorization',op.call_args.args[0].headers)

    @patch.object(n,'urlopen',side_effect=TimeoutError)
    def test_timeout_is_distinct_from_empty(self,op):
        self.assertEqual(n.stock_news('US','AAPL','APPLE INC')['status'],'unavailable')
        self.assertEqual(n.parse_feed(feed([])),[])

    def test_validation(self):
        for args in [('XX','AAPL','Apple'),('KR','123','x'),('US','AAPL',''),('US','AAPL','x'*121)]:
            with self.assertRaises(ValueError): n.stock_news(*args)

if __name__=='__main__': unittest.main()
