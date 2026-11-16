"""T0d follow-up 3: evaluate a keyless RSS alternative (Google News, pt-BR) as a fallback news source."""

import time
import xml.etree.ElementTree as ET  # noqa: S405 - spike parses a single trusted-host response; prod uses defusedxml

import httpx

URL = "https://news.google.com/rss/search"
for query in ['"síndrome respiratória aguda grave" when:30d', "SRAG when:14d"]:
    start = time.perf_counter()
    resp = httpx.get(URL, params={"q": query, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}, timeout=30,
                     headers={"User-Agent": "srag-sentinel-spike/0.1"}, follow_redirects=True)
    secs = time.perf_counter() - start
    print(f"\n[{query}] status={resp.status_code} latency={secs:.1f}s bytes={len(resp.content)} type={resp.headers.get('content-type')}")
    if resp.status_code != 200:
        continue
    root = ET.fromstring(resp.content)  # noqa: S314
    items = root.findall("./channel/item")
    print("n_items:", len(items))
    if items:
        print("item child tags:", sorted({c.tag for c in items[0]}))
    for it in items[:6]:
        src = it.find("source")
        print("-", it.findtext("pubDate"), "|", (src.text if src is not None else None), "|", (it.findtext("title") or "")[:85])
        print("   link:", (it.findtext("link") or "")[:90])
    time.sleep(6)
