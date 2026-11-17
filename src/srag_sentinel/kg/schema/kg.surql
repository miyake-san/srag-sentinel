-- Database `kg`: knowledge graph for GraphRAG (docs/specs/07, ADR 0016/0017/0019).
-- Nodes are SCHEMAFULL tables; edges are `TYPE RELATION ... ENFORCED` tables, so a relation can
-- only connect the declared node types. Generated nodes always carry provenance.

-- ---- static nodes (seeded) ------------------------------------------------------------
DEFINE TABLE OVERWRITE region SCHEMAFULL;
DEFINE FIELD OVERWRITE code ON region TYPE string;
DEFINE FIELD OVERWRITE name ON region TYPE string;

DEFINE TABLE OVERWRITE uf SCHEMAFULL;
DEFINE FIELD OVERWRITE code ON uf TYPE string ASSERT $value = /^(BR|[A-Z]{2})$/;
DEFINE FIELD OVERWRITE name ON uf TYPE string;
DEFINE FIELD OVERWRITE region ON uf TYPE option<record<region>>;

DEFINE TABLE OVERWRITE pathogen SCHEMAFULL;
DEFINE FIELD OVERWRITE name_pt ON pathogen TYPE string;
DEFINE FIELD OVERWRITE aliases ON pathogen TYPE array<string>;

-- ---- derived / generated nodes ---------------------------------------------------------
DEFINE TABLE OVERWRITE source SCHEMAFULL;
DEFINE FIELD OVERWRITE domain ON source TYPE string;
DEFINE FIELD OVERWRITE trust ON source TYPE float ASSERT $value >= 0 AND $value <= 1;

DEFINE TABLE OVERWRITE article SCHEMAFULL;
DEFINE FIELD OVERWRITE title ON article TYPE string;
DEFINE FIELD OVERWRITE snippet ON article TYPE string;
-- title and snippet joined: a FULLTEXT index covers exactly one column (spike T7b)
DEFINE FIELD OVERWRITE text ON article TYPE string;
DEFINE FIELD OVERWRITE url ON article TYPE string;
DEFINE FIELD OVERWRITE published_at ON article TYPE option<datetime>;
DEFINE FIELD OVERWRITE sha256 ON article TYPE string;
DEFINE FIELD OVERWRITE retrieved_at ON article TYPE datetime;
DEFINE FIELD OVERWRITE expires_at ON article TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON article TYPE string;

DEFINE TABLE OVERWRITE claim SCHEMAFULL;
DEFINE FIELD OVERWRITE type ON claim TYPE string
  ASSERT $value IN ["alert_level", "case_trend", "death_trend", "hospital_pressure",
                    "vaccination", "outbreak", "public_health_measure", "other"];
DEFINE FIELD OVERWRITE direction ON claim TYPE string
  ASSERT $value IN ["up", "down", "stable", "unknown"];
DEFINE FIELD OVERWRITE text ON claim TYPE string;
DEFINE FIELD OVERWRITE evidence_span ON claim TYPE string;
DEFINE FIELD OVERWRITE confidence ON claim TYPE float ASSERT $value >= 0 AND $value <= 1;
DEFINE FIELD OVERWRITE produced_by ON claim TYPE string;
DEFINE FIELD OVERWRITE judge ON claim TYPE option<object> FLEXIBLE;
DEFINE FIELD OVERWRITE run_id ON claim TYPE string;
DEFINE FIELD OVERWRITE created_at ON claim TYPE datetime;
DEFINE FIELD OVERWRITE expires_at ON claim TYPE datetime;

DEFINE TABLE OVERWRITE snapshot SCHEMAFULL;
DEFINE FIELD OVERWRITE scope ON snapshot TYPE string;
DEFINE FIELD OVERWRITE as_of ON snapshot TYPE string;
DEFINE FIELD OVERWRITE window_days ON snapshot TYPE int;
DEFINE FIELD OVERWRITE metrics ON snapshot TYPE object FLEXIBLE;
DEFINE FIELD OVERWRITE run_id ON snapshot TYPE string;
DEFINE FIELD OVERWRITE created_at ON snapshot TYPE datetime;

DEFINE TABLE OVERWRITE report SCHEMAFULL;
DEFINE FIELD OVERWRITE run_id ON report TYPE string;
DEFINE FIELD OVERWRITE generated_at ON report TYPE datetime;
DEFINE FIELD OVERWRITE status ON report TYPE string ASSERT $value IN ["ok", "degraded"];

DEFINE TABLE OVERWRITE summary SCHEMAFULL;
DEFINE FIELD OVERWRITE scope ON summary TYPE string;
DEFINE FIELD OVERWRITE text ON summary TYPE string;
DEFINE FIELD OVERWRITE evidence_ids ON summary TYPE array<string>;
DEFINE FIELD OVERWRITE produced_by ON summary TYPE string;
DEFINE FIELD OVERWRITE judge ON summary TYPE option<object> FLEXIBLE;
DEFINE FIELD OVERWRITE run_id ON summary TYPE string;
DEFINE FIELD OVERWRITE created_at ON summary TYPE datetime;
DEFINE FIELD OVERWRITE valid_until ON summary TYPE datetime;

-- Items that failed validation or the judge: kept out of the graph, kept for audit.
DEFINE TABLE OVERWRITE quarantine SCHEMAFULL;
DEFINE FIELD OVERWRITE kind ON quarantine TYPE string;
DEFINE FIELD OVERWRITE reason ON quarantine TYPE string;
DEFINE FIELD OVERWRITE article_id ON quarantine TYPE string;
DEFINE FIELD OVERWRITE run_id ON quarantine TYPE string;
DEFINE FIELD OVERWRITE produced_by ON quarantine TYPE string;
DEFINE FIELD OVERWRITE created_at ON quarantine TYPE datetime;

-- ---- edges (provenance on every generated edge) -----------------------------------------
DEFINE TABLE OVERWRITE in_region TYPE RELATION IN uf OUT region ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE adjacent_to TYPE RELATION IN uf OUT uf ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE published_by TYPE RELATION IN article OUT source ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE mentions TYPE RELATION IN article OUT uf ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE about TYPE RELATION IN article OUT pathogen ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE asserts TYPE RELATION IN article OUT claim ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE concerns TYPE RELATION IN claim OUT uf | pathogen ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE has_snapshot TYPE RELATION IN uf OUT snapshot ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE describes TYPE RELATION IN report OUT snapshot ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE cites TYPE RELATION IN report OUT article | claim | summary ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE summarizes TYPE RELATION IN summary OUT region | pathogen ENFORCED SCHEMAFULL;

DEFINE FIELD OVERWRITE produced_by ON in_region TYPE string;
DEFINE FIELD OVERWRITE created_at ON in_region TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON in_region TYPE option<string>;
DEFINE FIELD OVERWRITE produced_by ON adjacent_to TYPE string;
DEFINE FIELD OVERWRITE created_at ON adjacent_to TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON adjacent_to TYPE option<string>;
DEFINE FIELD OVERWRITE produced_by ON published_by TYPE string;
DEFINE FIELD OVERWRITE created_at ON published_by TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON published_by TYPE option<string>;
DEFINE FIELD OVERWRITE produced_by ON mentions TYPE string;
DEFINE FIELD OVERWRITE created_at ON mentions TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON mentions TYPE option<string>;
DEFINE FIELD OVERWRITE produced_by ON about TYPE string;
DEFINE FIELD OVERWRITE created_at ON about TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON about TYPE option<string>;
DEFINE FIELD OVERWRITE produced_by ON asserts TYPE string;
DEFINE FIELD OVERWRITE created_at ON asserts TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON asserts TYPE option<string>;
DEFINE FIELD OVERWRITE produced_by ON concerns TYPE string;
DEFINE FIELD OVERWRITE created_at ON concerns TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON concerns TYPE option<string>;
DEFINE FIELD OVERWRITE produced_by ON has_snapshot TYPE string;
DEFINE FIELD OVERWRITE created_at ON has_snapshot TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON has_snapshot TYPE option<string>;
DEFINE FIELD OVERWRITE produced_by ON describes TYPE string;
DEFINE FIELD OVERWRITE created_at ON describes TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON describes TYPE option<string>;
DEFINE FIELD OVERWRITE produced_by ON cites TYPE string;
DEFINE FIELD OVERWRITE created_at ON cites TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON cites TYPE option<string>;
DEFINE FIELD OVERWRITE produced_by ON summarizes TYPE string;
DEFINE FIELD OVERWRITE created_at ON summarizes TYPE datetime;
DEFINE FIELD OVERWRITE run_id ON summarizes TYPE option<string>;

-- ---- indexes ---------------------------------------------------------------------------
-- pt-BR analyzer: accents folded, snowball stems. The stemmer does not unify -ão/-ões nor
-- vacina/vacinação, so retrieval expands query terms with a lexicon (kg/lexicon.py).
DEFINE ANALYZER OVERWRITE pt_br TOKENIZERS class FILTERS lowercase, ascii, snowball(portuguese);
DEFINE INDEX OVERWRITE article_text ON article FIELDS text FULLTEXT ANALYZER pt_br BM25;
DEFINE INDEX OVERWRITE claim_text ON claim FIELDS text FULLTEXT ANALYZER pt_br BM25;
DEFINE INDEX OVERWRITE uf_code ON uf FIELDS code UNIQUE;
DEFINE INDEX OVERWRITE claim_expiry ON claim FIELDS expires_at;
DEFINE INDEX OVERWRITE snapshot_scope ON snapshot FIELDS scope, as_of;
