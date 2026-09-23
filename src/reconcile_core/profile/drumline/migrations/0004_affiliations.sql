-- 0004_affiliations.sql — drumline membership: seasons, sections, roles, and
-- cell-exact provenance for every roster claim.
--
-- The beatrack historical roster is the provenance root for 371 alumni: a
-- 71-row x 116-column grid where a row is a slot inside a band, a column is a
-- season, and the cell is whoever held that slot that season. `affiliations`
-- is the structured form of that grid (and of the prose notes it replaced);
-- `sources` + `source_ref` keep every claim traceable to the exact cell, so a
-- parser or transcription mistake stays recoverable.
--
-- Sections and roles are lookup tables, not free text: the source sheet spells
-- the same band several ways, and a word list beside the data is what drifts.
-- `Staff` is a role, never a section.
--
-- IF NOT EXISTS so an imported legacy DB that already carries these tables
-- migrates cleanly.

CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY AUTOINCREMENT, name
  TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, url TEXT, fetched_at TEXT, sha256
  TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS idx_sources_sha ON sources(sha256);

CREATE TABLE IF NOT EXISTS ensembles (KEY TEXT PRIMARY KEY, label TEXT NOT
  NULL);

CREATE TABLE IF NOT EXISTS sections (KEY TEXT PRIMARY KEY, label TEXT NOT NULL,
  sort INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS roles (KEY TEXT PRIMARY KEY, label TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS affiliations (id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  ensemble_key TEXT NOT NULL REFERENCES ensembles(KEY), role_key TEXT NOT NULL
  REFERENCES roles(KEY), season_year INTEGER NOT NULL, season_label TEXT NOT
  NULL DEFAULT '', section_key TEXT REFERENCES sections(KEY), unit TEXT NOT NULL
  DEFAULT '', slot INTEGER, source_id INTEGER REFERENCES sources(id) ON DELETE
  SET NULL, source_ref TEXT NOT NULL DEFAULT '', raw_text TEXT NOT NULL DEFAULT
  '', confidence TEXT NOT NULL DEFAULT '', review_status TEXT NOT NULL DEFAULT
  '', note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT
  (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));

-- Uniqueness with a COALESCE key: a staff affiliation carries no section, and
-- SQLite treats NULLs as distinct in a plain UNIQUE constraint.
CREATE UNIQUE INDEX IF NOT EXISTS ux_affiliations ON affiliations(entity_id,
  ensemble_key, role_key, season_year, coalesce(section_key, ''), source_id);
CREATE INDEX IF NOT EXISTS idx_affiliations_entity ON affiliations(entity_id);
CREATE INDEX IF NOT EXISTS idx_affiliations_season ON affiliations(ensemble_key,
  season_year, section_key);

CREATE TRIGGER IF NOT EXISTS trg_affiliations_updated_at AFTER UPDATE ON
  affiliations FOR EACH ROW BEGIN UPDATE affiliations SET updated_at =
  datetime('now')
WHERE id = OLD.id;
END;

INSERT OR IGNORE INTO ensembles (KEY, label)
VALUES ('illini-drumline', 'Illini Drumline');

INSERT OR IGNORE INTO sections (KEY, label, sort)
VALUES ('snares', 'Snares', 1), ('tenors', 'Tenors', 2), ('basses', 'Basses',
  3), ('cymbals', 'Cymbals', 4), ('glockenspiels',
  'Marching Glockenspiels & Bell Lyres', 5), ('timpani', 'Timpani', 6);

INSERT OR IGNORE INTO roles (KEY, label)
VALUES ('member', 'Member'), ('staff', 'Staff');
