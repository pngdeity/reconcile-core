-- 0006_membership_details.sql — named slots and outreach provenance.
-- Two additions decided 2026-09-23:
--   * affiliations.slot_label — a position inside a section that is not a number.
--     The audition documents name the seventh bass drum `Kicker`; that is a
--     position within `basses`, never a separate instrument or section, so it is
--     captured as a label while `slot` stays NULL.
--   * drumline_outreach.verification_source / notes_source — provenance for the
--     two facts that today live in BOTH `drumline_outreach` and `aliases`
--     (alias types `tracker_verification` 389 rows and `tracker_notes` 80 rows).
--     The outreach columns are the readers' source of truth; the alias carriers
--     are being retired, so their `source` is copied here first and nothing is
--     lost. `Tracker.csv` is git-ignored and is NOT a durable provenance record.
-- Plain ALTER TABLE, matching 0005; the runner records applied versions, so this
-- executes once per store.

ALTER TABLE affiliations ADD COLUMN slot_label TEXT NOT NULL DEFAULT '';

ALTER TABLE drumline_outreach ADD COLUMN verification_source TEXT NOT NULL
  DEFAULT '';
ALTER TABLE drumline_outreach ADD COLUMN notes_source TEXT NOT NULL DEFAULT '';
