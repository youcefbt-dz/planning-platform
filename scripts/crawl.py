"""Smoke crawl: follow every internal GET link from the demo orgs and report errors / leaked i18n keys."""
import re, sys
from urllib.parse import urljoin, urlparse
from app import create_app

KEY = re.compile(r">\s*((?:common|goals|initiatives|strategy|reports|site|status|settings|shell|auth|errors|time|role|demo|activity|nav)\.[a-z_]+(?:\.[a-z_]+)*)\s*<|(?:placeholder|aria-label|title|alt)=\"((?:common|goals|initiatives|strategy|reports|site|status|settings|shell|auth|errors|time|role|demo|activity)\.[a-z_]+(?:\.[a-z_]+)*)\"")
app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
c = app.test_client()
bad = 0
seen = set()
for lang, slug in (("ar", "demo"), ("en", "demo-en"), ("fr", "demo-fr")):
    q = [f"/app/{slug}/?lang={lang}", f"/?lang={lang}", f"/login?lang={lang}", f"/register?lang={lang}"]
    while q:
        url = q.pop(0)
        path = urlparse(url).path
        key = (lang, path + '?' + ','.join(sorted(k for k in re.findall(r'[?&]([a-z_]+)=', url) if k != 'lang')))
        if len(seen) > 400: break
        if key in seen: continue
        seen.add(key)
        print(lang, url, flush=True)
        r = c.get(url, follow_redirects=True)
        html = r.get_data(as_text=True)
        if r.status_code >= 400:
            print(f"[{lang}] {r.status_code} {url}"); bad += 1; continue
        leaks = [a or b for a, b in KEY.findall(html)]
        if leaks:
            print(f"[{lang}] LEAK {url}: {sorted(set(leaks))[:6]}"); bad += 1
        for href in re.findall(r'href="([^"#]+)"', html):
            if href.startswith(("/app/", "/")) and not href.startswith(("/static", "//")) and "logout" not in href and ".csv" not in href:
                u = urljoin(url, href)
                if "lang=" not in u: u += ("&" if "?" in u else "?") + f"lang={lang}"
                if u not in q: q.append(u)
print(len(seen), "pages crawled,", bad, "problems")
sys.exit(1 if bad else 0)
