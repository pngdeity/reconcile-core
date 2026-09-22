-- 0001_init.sql — canonical contacts store, schema v1.
--
-- The store is the single source of truth for entities and their contact
-- points. Generated files are projections of this store.
--
-- Rules: never include transaction control (BEGIN/COMMIT) in a migration; the
-- runner wraps each migration in a transaction. The runner owns
-- `schema_version`, so migrations must not create or alter it.

CREATE TABLE entities (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT NOT NULL
  UNIQUE, type TEXT NOT NULL CHECK (type IN ('person','org','service','group')),
  privacy_tier TEXT NOT NULL DEFAULT 'standard' CHECK (privacy_tier IN
  ('standard','restricted')), display_name TEXT, first_name TEXT, middle_name
  TEXT, last_name TEXT, nickname TEXT, org_name TEXT, title TEXT, department
  TEXT, birthday TEXT, notes TEXT, created_at TEXT NOT NULL DEFAULT
  (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));

CREATE TRIGGER trg_entities_updated_at AFTER UPDATE ON entities FOR EACH ROW
  BEGIN UPDATE entities SET updated_at = datetime('now')
WHERE id = OLD.id;
END;

-- Identity unification: every platform identity (linkedin, discord, matrix,
-- google, ...) is an external ref on the entity, not a separate mapping table.
CREATE TABLE external_refs (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id
  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE, source TEXT NOT
  NULL, ref_value TEXT NOT NULL, UNIQUE (source, ref_value));
CREATE INDEX idx_external_refs_entity ON external_refs(entity_id);

CREATE TABLE contact_points (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id
  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE, kind TEXT NOT NULL
  CHECK (kind IN ('email','phone','address','url','handle')), value TEXT NOT
  NULL, label_raw TEXT, label_norm TEXT, service TEXT, is_primary INTEGER NOT
  NULL DEFAULT 0 CHECK (is_primary IN (0,1)), position INTEGER, source TEXT,
  first_seen TEXT, last_seen TEXT);
CREATE INDEX idx_contact_points_entity ON contact_points(entity_id);
CREATE INDEX idx_contact_points_kind_value ON contact_points(kind, value);

CREATE TABLE addresses (contact_point_id INTEGER PRIMARY KEY REFERENCES
  contact_points(id) ON DELETE CASCADE, street TEXT, city TEXT, region TEXT,
  postal TEXT, country TEXT, pobox TEXT, extended TEXT, formatted TEXT);

CREATE TABLE aliases (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER
  NOT NULL REFERENCES entities(id) ON DELETE CASCADE, alias_type TEXT NOT NULL,
  alias_value TEXT NOT NULL, source TEXT, position INTEGER, UNIQUE (entity_id,
  alias_type, alias_value));
CREATE INDEX idx_aliases_entity ON aliases(entity_id);

CREATE TABLE segments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL
  UNIQUE, description TEXT, definition TEXT);

CREATE TABLE segment_members (segment_id INTEGER NOT NULL REFERENCES
  segments(id) ON DELETE CASCADE, entity_id INTEGER NOT NULL REFERENCES
  entities(id) ON DELETE CASCADE, added_at TEXT NOT NULL DEFAULT
  (datetime('now')), PRIMARY KEY (segment_id, entity_id));

CREATE TABLE decision_state (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id
  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE, contact_point_id
  INTEGER REFERENCES contact_points(id) ON DELETE SET NULL, channel TEXT, status
  TEXT NOT NULL, reason TEXT, source TEXT, observed_at TEXT);
CREATE INDEX idx_decision_state_entity ON decision_state(entity_id);

-- Status observed outside the store (e.g. group membership, bounce, block),
-- recorded as dated snapshots.
CREATE TABLE external_status (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id
  INTEGER REFERENCES entities(id) ON DELETE SET NULL, channel TEXT NOT NULL,
  address TEXT NOT NULL, status TEXT NOT NULL, email_status TEXT, nickname TEXT,
  source TEXT, observed_at TEXT NOT NULL);
CREATE UNIQUE INDEX ux_external_status ON external_status(channel, address,
  observed_at);
CREATE INDEX idx_external_status_address ON external_status(channel, address);
CREATE INDEX idx_external_status_entity ON external_status(entity_id);

-- Reconciliation bookkeeping: platform identities awaiting a Google contact.
CREATE TABLE unresolved_identities (platform TEXT NOT NULL, source_id TEXT NOT
  NULL, display_name TEXT, last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (platform, source_id));

CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, event_time
  TIMESTAMP DEFAULT CURRENT_TIMESTAMP, resource_name TEXT, action TEXT, delta
  TEXT);
