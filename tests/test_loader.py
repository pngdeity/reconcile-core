import pytest
from reconcile_core.loader import EtagsConflictError


class TestEtagsConflictError:
    def test_is_gws_error_subclass(self):
        from reconcile_core.google_adapter import GWSCommandError
        assert issubclass(EtagsConflictError, GWSCommandError)

    def test_inherits_from_exception(self):
        assert issubclass(EtagsConflictError, Exception)

    def test_instantiation(self):
        err = EtagsConflictError("message", "stderr output")
        assert str(err) == "message"
        assert err.stderr == "stderr output"
