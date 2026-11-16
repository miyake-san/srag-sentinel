-- Database `audit`: append-only, hash-chained trail (docs/specs/05, ADR 0013).
-- The application signs in as the record-access user `audit_writer`: it may CREATE and SELECT
-- audit events but never UPDATE or DELETE them. System users (EDITOR/OWNER/root) bypass table
-- permissions, so the app never receives those credentials; tampering by them is detected by
-- `srag-sentinel audit verify` and by the external JSONL export.

DEFINE TABLE OVERWRITE svc SCHEMAFULL PERMISSIONS NONE;
DEFINE FIELD OVERWRITE name ON svc TYPE string;
DEFINE FIELD OVERWRITE pass ON svc TYPE string;

DEFINE TABLE OVERWRITE audit_event SCHEMAFULL
  PERMISSIONS
    FOR select FULL
    FOR create WHERE $access = 'audit_writer'
    FOR update, delete NONE;

DEFINE FIELD OVERWRITE schema_version ON audit_event TYPE string READONLY;
DEFINE FIELD OVERWRITE seq ON audit_event TYPE int READONLY;
DEFINE FIELD OVERWRITE ts ON audit_event TYPE string READONLY;
DEFINE FIELD OVERWRITE run_id ON audit_event TYPE string READONLY;
DEFINE FIELD OVERWRITE actor ON audit_event TYPE string READONLY;
DEFINE FIELD OVERWRITE node ON audit_event TYPE string READONLY;
DEFINE FIELD OVERWRITE event ON audit_event TYPE string READONLY;
DEFINE FIELD OVERWRITE inputs_hash ON audit_event TYPE option<string> READONLY;
DEFINE FIELD OVERWRITE outputs_hash ON audit_event TYPE option<string> READONLY;
DEFINE FIELD OVERWRITE details ON audit_event TYPE object FLEXIBLE READONLY;
DEFINE FIELD OVERWRITE prev_hash ON audit_event TYPE string READONLY;
DEFINE FIELD OVERWRITE hash ON audit_event TYPE string READONLY;

-- A unique `seq` makes a forked chain (two writers racing) fail loudly instead of silently.
DEFINE INDEX OVERWRITE seq_uq ON audit_event FIELDS seq UNIQUE;
DEFINE INDEX OVERWRITE run_idx ON audit_event FIELDS run_id;

DEFINE ACCESS OVERWRITE audit_writer ON DATABASE TYPE RECORD
  SIGNIN (SELECT * FROM svc WHERE name = $name AND crypto::argon2::compare(pass, $pass))
  DURATION FOR TOKEN 1h, FOR SESSION 12h;
