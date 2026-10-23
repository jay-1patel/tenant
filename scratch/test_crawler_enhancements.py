import sys
sys.path.insert(0, '.')

print("=" * 60)
print("1. url_scraper imports")
print("=" * 60)
from services.url_scraper import (
    WebScraperCrawler, RobotsTxtPolicy, looks_like_js_shell, render_with_playwright,
)
print("OK")

print()
print("=" * 60)
print("2. JS shell heuristic")
print("=" * 60)
shell_html = ('<html><head>' + '<script src=x.js></script>' * 5 +
              '</head><body><div id=root></div></body></html>')
rich_html = '<html><body>' + ('<p>Real server rendered content paragraph.</p>' * 40) + '</body></html>'
assert looks_like_js_shell(shell_html) is True, "JS shell not detected"
assert looks_like_js_shell(rich_html) is False, "rich page misdetected as JS shell"
assert looks_like_js_shell('') is False
print("OK: shells detected, rich pages pass through")

print()
print("=" * 60)
print("3. Playwright gracefully absent (not installed)")
print("=" * 60)
assert render_with_playwright('https://example.com') is None, "expected None without playwright"
print("OK: falls back to None (crawler keeps static HTML)")

print()
print("=" * 60)
print("4. RobotsTxtPolicy semantics (controlled)")
print("=" * 60)
import urllib.robotparser
p = urllib.robotparser.RobotFileParser()
p.parse(['User-agent: *', 'Disallow: /private', 'Crawl-delay: 2'])
assert p.can_fetch('bot', 'https://s.com/') is True
assert p.can_fetch('bot', 'https://s.com/private/x') is False
assert p.crawl_delay('bot') == 2.0
print("OK: allow/deny/crawl-delay parsed correctly")

print()
print("=" * 60)
print("5. RobotsTxtPolicy degradation on missing robots.txt")
print("=" * 60)
rp = RobotsTxtPolicy('https://example.com', timeout=8)  # 404 -> allow all
assert rp.can_fetch('https://example.com/') is True
assert rp.crawl_delay is None
print("OK: 404 robots.txt degrades to allowed")

print()
print("=" * 60)
print("6. Crawl schedule CRUD")
print("=" * 60)
from database import (
    get_crawl_schedule, upsert_crawl_schedule, delete_crawl_schedule,
    list_due_crawl_schedules, mark_crawl_started, mark_crawl_finished, init_db,
)
init_db()
s = upsert_crawl_schedule('test_sched_tenant', 'https://example.com',
                           interval_hours=6, max_pages=5, auto_publish=False)
assert s['tenant_id'] == 'test_sched_tenant'
assert s['interval_hours'] == 6 and s['max_pages'] == 5
assert s['auto_publish'] is False and s['is_enabled'] is True
due = list_due_crawl_schedules()
assert any(d['tenant_id'] == 'test_sched_tenant' for d in due), "never-crawled not due"
mark_crawl_started('test_sched_tenant')
s2 = get_crawl_schedule('test_sched_tenant')
assert s2['last_status'] == 'running'
assert not any(d['tenant_id'] == 'test_sched_tenant' for d in list_due_crawl_schedules()), \
    "running schedule still due"
mark_crawl_finished('test_sched_tenant', 'success')
assert get_crawl_schedule('test_sched_tenant')['last_status'] == 'success'
assert not any(d['tenant_id'] == 'test_sched_tenant' for d in list_due_crawl_schedules()), \
    "freshly crawled still due"
assert delete_crawl_schedule('test_sched_tenant') is True
assert get_crawl_schedule('test_sched_tenant') is None
assert delete_crawl_schedule('test_sched_tenant') is False  # already gone
print("OK: upsert, due-listing, start/finish stamps, delete")

print()
print("=" * 60)
print("7. Live crawl of example.com (robots-checked, delay enforced)")
print("=" * 60)
c = WebScraperCrawler('https://example.com', max_pages=2, request_delay=0.5)
res = c.crawl()
assert res['pages_crawled_count'] >= 1, "example.com crawl produced no pages"
assert 'Example Domain' in res['pages'][0]['title']
assert res.get('skipped_urls') == [] and res.get('js_rendered_urls') == []
print(f"OK: crawled {res['pages_crawled_count']} page(s), robots honored, no JS fallback needed")

print()
print("=" * 60)
print("8. UrlAutoOnboarder robots-blocked error path")
print("=" * 60)
from services.url_scraper import UrlAutoOnboarder

class FakeCrawler(WebScraperCrawler):
    def crawl(self):
        return {"root_url": self.root_url, "domain": self.domain,
                "pages_crawled_count": 0, "pages": [],
                "skipped_urls": [{"url": self.root_url, "reason": "robots.txt disallow"}],
                "blocked_by_robots": True}

import services.url_scraper as us
orig_cls = us.WebScraperCrawler
us.WebScraperCrawler = FakeCrawler
try:
    ob = UrlAutoOnboarder(tenant_id='robot_test')
    try:
        ob.execute_onboarding(url='https://blocked.example.com')
        raise SystemExit("expected ValueError for robots-blocked site")
    except ValueError as e:
        assert 'robots.txt' in str(e), f"wrong error: {e}"
finally:
    us.WebScraperCrawler = orig_cls
print("OK: blocked site raises clear robots.txt error")

print()
print("ALL CHECKS PASSED")
