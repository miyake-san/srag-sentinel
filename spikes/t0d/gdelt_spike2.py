"""T0d follow-up: respect the documented 1 request / 5 s limit and inspect the JSON shape."""

import time

import httpx

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERY = '("síndrome respiratória aguda grave" OR SRAG OR influenza OR "vírus sincicial") sourcelang:portuguese sourcecountry:brazil'
params = {"query": QUERY, "mode": "artlist", "format": "json", "maxrecords": "10", "timespan": "14d", "sort": "datedesc"}

time.sleep(90)  # let any shared-IP throttling clear (earlier spike fired 6 rapid requests)
for attempt in range(2):
    start = time.perf_counter()
    resp = httpx.get(URL, params=params, timeout=45, headers={"User-Agent": "srag-sentinel-spike/0.1"})
    secs = time.perf_counter() - start
    print(f"attempt {attempt + 1}: status={resp.status_code} latency={secs:.1f}s bytes={len(resp.content)}")
    if resp.status_code == 200:
        data = resp.json()
        arts = data.get("articles", [])
        print("top-level keys:", list(data.keys()), "n_articles:", len(arts))
        if arts:
            print("article keys:", sorted(arts[0].keys()))
        for a in arts[:10]:
            print("-", a.get("seendate"), "|", a.get("domain"), "|", a.get("language"), "|", (a.get("title") or "")[:90])
        break
    time.sleep(20)  # well above the documented 5 s spacing
