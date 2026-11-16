-- Database `app`: generated reports and news cache.

DEFINE TABLE OVERWRITE report SCHEMALESS;

DEFINE TABLE OVERWRITE news_cache SCHEMALESS;
DEFINE FIELD OVERWRITE cache_key ON news_cache TYPE string;
DEFINE FIELD OVERWRITE expires_at ON news_cache TYPE datetime;
DEFINE INDEX OVERWRITE cache_key_idx ON news_cache FIELDS cache_key UNIQUE;
