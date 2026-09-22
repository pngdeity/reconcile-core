"""Illini Drumline profile: membership, outreach overlay, and member export.

Layered on the generic canonical store. PII-bearing inputs (Tracker.csv, the
``manual_*`` JSONs, the store itself) stay outside the repository.

This package intentionally re-exports nothing at import time, so the CLI
(``python -m reconcile_core.profile.drumline <command>``) runs its submodules
without runpy warnings. Import from the submodules directly:

- ``migrate``          core + drumline migrations
- ``import_drumline``  Tracker membership, segment, decision state
- ``name_resolutions`` manual name resolutions
- ``import_master``    legacy master seed (outreach overlay)
- ``export_members``   person-level member CSV
"""
