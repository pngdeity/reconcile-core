-- 0005_alias_provenance.sql — claim-level provenance for name claims.
--
-- An alias is a claim about a person's name, not a bare string: `(Zoidberg)`
-- in the roster is a nickname, `(Zaun)` in `Stacy (Zaun) Eifert` is a former
-- name, and a merged misspelling is a roster spelling. Each carries where it
-- came from and how strong it is, so the answer to "who says this?" is data.
--
-- alias_type vocabulary in use:
--   name            a full-name form of the person
--   nickname        a known nickname (inventory; not necessarily used)
--   former_name     a previous full name
--   maiden_name     a birth/maiden surname
--   legal_name      a legal full name differing from display_name
--   roster_spelling a spelling kept from a source after a fold
--   unit            a sub-unit / line marker (e.g. B-Line)
--   aka             a catch-all alternate form
--   tracker_verification / tracker_notes / relation / pronunciation /
--   slot_label      legacy import carriers (see docs/MEMBERSHIP-SCHEMA.md)
--
-- Confidence values: '' (unstated), 'verified', 'likely', 'uncertain'.

ALTER TABLE aliases ADD COLUMN confidence TEXT NOT NULL DEFAULT '';
ALTER TABLE aliases ADD COLUMN observed_at TEXT;
ALTER TABLE aliases ADD COLUMN source_ref TEXT NOT NULL DEFAULT '';
