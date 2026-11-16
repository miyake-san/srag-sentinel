"""T0d follow-up 2: which GDELT query shapes return Brazilian Portuguese health articles (10 s spacing)."""

import time

import httpx

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
VARIANTS = [
    "srag sourcelang:portuguese",
    '"síndrome respiratória aguda grave" sourcelang:portuguese',
    "influenza sourcecountry:BR sourcelang:portuguese",
    "(gripe OR influenza OR covid OR srag) sourcecountry:brazil",
    "(srag OR influenza OR covid) sourcelang:portuguese",
]

for i, query in enumerate(VARIANTS):
    if i:
        time.sleep(12)
    params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": "8", "timespan": "30d", "sort": "datedesc"}
    start = time.perf_counter()
    resp = httpx.get(URL, params=params, timeout=45, headers={"User-Agent": "srag-sentinel-spike/0.1"})
    secs = time.perf_counter() - start
    summary = f"status={resp.status_code} latency={secs:.1f}s bytes={len(resp.content)}"
    if resp.status_code == 200 and len(resp.content) > 2:
        try:
            arts = resp.json().get("articles", [])
        except ValueError:
            arts = []
            summary += " (non-JSON)"
        summary += f" n={len(arts)}"
        print(f"\n[{query}] {summary}")
        if arts:
            print("keys:", sorted(arts[0].keys()))
        for a in arts[:5]:
            print("-", a.get("seendate"), "|", a.get("domain"), "|", a.get("language"), "|", (a.get("title") or "")[:80])
    else:
        print(f"\n[{query}] {summary} head={resp.text[:80]!r}")
