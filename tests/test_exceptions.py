"""Tests for omega.exceptions hierarchy."""

import pytest

from omega.exceptions import (
    CloudSyncError,
    CoordinationError,
    EmbeddingError,
    HookError,
    OmegaError,
    StorageError,
    ValidationError,
)

ALL_EXCEPTIONS = [
    StorageError,
    EmbeddingError,
    CoordinationError,
    CloudSyncError,
    HookError,
    ValidationError,
]


class TestExceptionHierarchy:
    def test_omega_error_is_exception(self):
        assert issubclass(OmegaError, Exception)

    @pytest.mark.parametrize("exc_cls", ALL_EXCEPTIONS)
    def test_all_inherit_from_omega_error(self, exc_cls):
        assert issubclass(exc_cls, OmegaError)

    def test_exception_message_preserved(self):
        err = StorageError("disk full")
        assert str(err) == "disk full"
        assert isinstance(err, OmegaError)
        assert isinstance(err, Exception)

    def test_exceptions_catchable_as_base(self):
        with pytest.raises(OmegaError):
            raise StorageError("test")
        with pytest.raises(OmegaError):
            raise EmbeddingError("test")
        with pytest.raises(OmegaError):
            raise CoordinationError("test")

    def test_each_exception_is_distinct(self):
        classes = set(ALL_EXCEPTIONS + [OmegaError])
        assert len(classes) == len(ALL_EXCEPTIONS) + 1
        # Each should NOT be caught by a sibling
        with pytest.raises(StorageError):
            raise StorageError("x")
        # StorageError should not match EmbeddingError
        with pytest.raises(StorageError):
            try:
                raise StorageError("x")
            except EmbeddingError:
                pytest.fail("StorageError caught as EmbeddingError")
