"""T0b spike: profile the remote SRAG Parquet with column projection (aggregates only).

Only the schema and per-column value counts are printed; no individual rows.
Usage: python profile_parquet.py <parquet_url>
"""

import sys

import polars as pl

URL = sys.argv[1]
CANDIDATES = ["DT_NOTIFIC", "DT_SIN_PRI", "SG_UF_NOT", "SG_UF", "HOSPITAL", "UTI", "EVOLUCAO",
              "VACINA_COV", "VACINA", "CLASSI_FIN", "DT_INTERNA", "DT_EVOLUCA"]

lf = pl.scan_parquet(URL)
schema = lf.collect_schema()
print(f"n_columns={len(schema)}")
print("columns:", ", ".join(schema.names()))
print("candidate dtypes:", {c: str(schema[c]) for c in CANDIDATES if c in schema})
print("missing candidates:", [c for c in CANDIDATES if c not in schema])

present = [c for c in CANDIDATES if c in schema]
df = lf.select(present).collect()
print(f"n_rows={df.height}")

for col in ["HOSPITAL", "UTI", "EVOLUCAO", "VACINA_COV", "VACINA", "CLASSI_FIN", "SG_UF_NOT"]:
    if col in df.columns:
        counts = df[col].cast(pl.Utf8).value_counts().sort("count", descending=True).head(12)
        print(f"\n{col}: nulls={df[col].null_count()}")
        print(counts)

for col in ["DT_NOTIFIC", "DT_SIN_PRI"]:
    if col in df.columns:
        s = df[col]
        print(f"\n{col}: dtype={s.dtype} nulls={s.null_count()} sample_min/max(as str)=",
              s.cast(pl.Utf8).min(), s.cast(pl.Utf8).max())
