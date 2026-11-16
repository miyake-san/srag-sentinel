"""T0b spike: notification-lag and monthly volume profile across the 2025 and 2026 files.

Aggregates only (no individual rows). Usage: python profile_dates.py <url_2025> <url_2026>
"""

import sys

import polars as pl

COLS = ["DT_NOTIFIC", "DT_SIN_PRI", "HOSPITAL"]
frames = [pl.scan_parquet(url).select(COLS).collect().with_columns(pl.lit(url[-30:]).alias("src"))
          for url in sys.argv[1:]]
df = pl.concat(frames).with_columns(
    (pl.col("DT_NOTIFIC") - pl.col("DT_SIN_PRI")).dt.total_days().alias("lag_days")
)
print(f"rows={df.height}")
print("lag_days describe:")
print(df["lag_days"].describe())
for label, cond in [
    ("lag < 0", pl.col("lag_days") < 0),
    ("lag > 30", pl.col("lag_days") > 30),
    ("lag > 90", pl.col("lag_days") > 90),
    ("lag > 180", pl.col("lag_days") > 180),
    ("DT_NOTIFIC > 2026-11-16", pl.col("DT_NOTIFIC") > pl.datetime(2026, 11, 16)),
    ("DT_NOTIFIC < 2024-12-29", pl.col("DT_NOTIFIC") < pl.datetime(2024, 12, 29)),
]:
    print(f"{label}: {df.filter(cond).height}")

monthly = (
    df.with_columns(pl.col("DT_NOTIFIC").dt.strftime("%Y-%m").alias("ym"))
    .group_by("ym").agg(pl.len().alias("n")).sort("ym")
)
print("\nrows per DT_NOTIFIC month (both files):")
print(monthly.tail(20))
last = df.filter(pl.col("DT_NOTIFIC") >= pl.datetime(2026, 10, 1)).group_by(
    pl.col("DT_NOTIFIC").dt.date().alias("day")).agg(pl.len().alias("n")).sort("day")
print("\nlast 20 days:")
print(last.tail(20))
