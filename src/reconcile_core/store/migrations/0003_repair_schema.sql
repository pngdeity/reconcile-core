-- 0003_repair_schema.sql — restore baseline tables missing from imported stores.
--
-- `import_db.import_legacy_db` copies a legacy store and re-stamps
-- `schema_version` to the baseline without running `0001_init.sql`, so any
-- baseline table the source store lacked is never created. Observed on the
-- illini store (missing `audit_log` and `unresolved_identities`), which broke
-- audited merges until repaired by hand.
--
-- `CREATE TABLE IF NOT EXISTS` keeps this a no-op for healthy stores; the DDL is
-- identical to `0001_init.sql`.

CREATE TABLE IF NOT EXISTS unresolved_identities (platform TEXT NOT NULL,
  source_id TEXT NOT NULL, display_name TEXT, last_seen TIMESTAMP DEFAULT
  CURRENT_TIMESTAMP, PRIMARY KEY (platform, source_id));

CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, resource_name TEXT, action
  TEXT, delta TEXT);
