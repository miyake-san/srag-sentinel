-- Database `data`: daily SRAG aggregates per UF. Only aggregates are stored (no patient rows).
-- Applied by `srag-sentinel db init`; every statement is idempotent (OVERWRITE).

DEFINE TABLE OVERWRITE srag_daily SCHEMAFULL;

DEFINE FIELD OVERWRITE uf ON srag_daily TYPE string ASSERT $value = /^[A-Z]{2}$/;
-- ISO date (YYYY-MM-DD) of notification; strings sort chronologically and avoid time zones.
DEFINE FIELD OVERWRITE day ON srag_daily TYPE string ASSERT $value = /^\d{4}-\d{2}-\d{2}$/;
DEFINE FIELD OVERWRITE cases ON srag_daily TYPE int ASSERT $value >= 0;
DEFINE FIELD OVERWRITE hosp_cases ON srag_daily TYPE int ASSERT $value >= 0;
DEFINE FIELD OVERWRITE outcome_known ON srag_daily TYPE int ASSERT $value >= 0;
DEFINE FIELD OVERWRITE deaths ON srag_daily TYPE int ASSERT $value >= 0;
DEFINE FIELD OVERWRITE uti_known ON srag_daily TYPE int ASSERT $value >= 0;
DEFINE FIELD OVERWRITE uti_yes ON srag_daily TYPE int ASSERT $value >= 0;
DEFINE FIELD OVERWRITE vac_cov_known ON srag_daily TYPE int ASSERT $value >= 0;
DEFINE FIELD OVERWRITE vac_cov_yes ON srag_daily TYPE int ASSERT $value >= 0;
DEFINE FIELD OVERWRITE vac_flu_known ON srag_daily TYPE int ASSERT $value >= 0;
DEFINE FIELD OVERWRITE vac_flu_yes ON srag_daily TYPE int ASSERT $value >= 0;

DEFINE INDEX OVERWRITE uf_day ON srag_daily FIELDS uf, day UNIQUE;
DEFINE INDEX OVERWRITE day_idx ON srag_daily FIELDS day;

DEFINE TABLE OVERWRITE ingest_manifest SCHEMAFULL;
DEFINE FIELD OVERWRITE source_url ON ingest_manifest TYPE string;
DEFINE FIELD OVERWRITE retrieved_at ON ingest_manifest TYPE datetime;
DEFINE FIELD OVERWRITE rows_read ON ingest_manifest TYPE int;
DEFINE FIELD OVERWRITE rows_kept ON ingest_manifest TYPE int;
DEFINE FIELD OVERWRITE dropped ON ingest_manifest TYPE object FLEXIBLE;
DEFINE FIELD OVERWRITE snapshot_sha256 ON ingest_manifest TYPE string;
