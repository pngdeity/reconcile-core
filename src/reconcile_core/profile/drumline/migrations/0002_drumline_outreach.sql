-- 0002_drumline_outreach.sql — per-person drumline outreach/status overlay.
-- Curated facts from the legacy drumline master list (dump presence, outreach
-- and review status, verification). Identity and contact points stay in
-- entities/contact_points; this table holds only the status overlay.
-- IF NOT EXISTS so an imported legacy DB that already carries the table
-- migrates cleanly.

CREATE TABLE IF NOT EXISTS drumline_outreach (entity_id INTEGER PRIMARY KEY
  REFERENCES entities(id) ON DELETE CASCADE, verification TEXT NOT NULL DEFAULT
  '', dumps_seen TEXT NOT NULL DEFAULT '', reached_dumps_1_6 TEXT NOT NULL
  DEFAULT '', reached_dump_0 TEXT NOT NULL DEFAULT '', has_email TEXT NOT NULL
  DEFAULT '', has_phone TEXT NOT NULL DEFAULT '', tracker_notes TEXT NOT NULL
  DEFAULT '', needs_first_outreach TEXT NOT NULL DEFAULT '', review_status TEXT
  NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT (datetime('now')));
