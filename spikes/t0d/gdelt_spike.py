"""T0d spike: GDELT DOC 2.0 for Brazilian Portuguese SRAG news — shape, latency, relevance, 429 behavior."""

import time

import httpx

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERY = '("síndrome respiratória aguda grave" OR SRAG OR influenza OR "vírus sincicial") sourcelang:portuguese sourcecountry:brazil'


def fetch(params: dict[str, str]) -> tuple[int, float, httpx.Response]:
    start = time.perf_counter()
    resp = httpx.get(URL, params=params, timeout=30, headers={"User-Agent": "srag-sentinel-spike/0.1"})
    return resp.status_code, time.perf_counter() - start, resp


params = {"query": QUERY, "mode": "artlist", "format": "json", "maxrecords": "10",
          "timespan": "14d", "sort": "datedesc"}
status, secs, resp = fetch(params)
print(f"status={status} latency={secs:.2f}s content_type={resp.headers.get('content-type')} bytes={len(resp.content)}")
try:
    data = resp.json()
    arts = data.get("articles", [])
    print("top-level keys:", list(data.keys()), "n_articles:", len(arts))
    if arts:
        print("article keys:", sorted(arts[0].keys()))
    for a in arts[:10]:
        print("-", a.get("seendate"), "|", a.get("domain"), "|", a.get("language"), "|", (a.get("title") or "")[:90])
except ValueError:
    print("non-JSON body head:", resp.text[:300])

# Rapid-fire to observe rate limiting behavior (6 requests, no delay)
codes = []
for _ in range(6):
    s, t, r = fetch({**params, "maxrecords": "5"})
    codes.append((s, round(t, 2), r.headers.get("retry-after")))
print("rapid-fire (status, secs, retry-after):", codes)

# Malformed query behavior
s, t, r = fetch({**params, "query": "a"})
print("short-query status:", s, "body head:", r.text[:160].replace("\n", " "))
