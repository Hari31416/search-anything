"""Device selection must respect explicit overrides and unavailable GPUs."""

import pytest
import torch

from search_anything.devices import resolve_device
from search_anything.settings import Settings


@pytest.mark.parametrize(
    ("available", "requested", "expected"),
    [
        (True, "auto", "mps"),
        (False, "auto", "cpu"),
        (True, "cpu", "cpu"),
        (False, "cpu", "cpu"),
        (True, "mps", "mps"),
    ],
)
def test_device_selection(monkeypatch, available, requested, expected):
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: available)
    assert resolve_device(requested) == expected


def test_explicit_gpu_does_not_silently_fall_back(monkeypatch):
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="MPS GPU is unavailable"):
        resolve_device("mps")


def test_settings_reject_unknown_device():
    with pytest.raises(ValueError):
        Settings(embedding_device="typo", _env_file=None)


def test_whisper_alignment_moves_to_cpu_before_float64(monkeypatch):
    from whisper import timing
    from search_anything.media import _whisper_dtw_cpu

    operations = []

    class Matrix:
        def cpu(self):
            operations.append("cpu")
            return self

        def double(self):
            assert operations == ["cpu"]
            operations.append("double")
            return self

        def numpy(self):
            operations.append("numpy")
            return "matrix"

    monkeypatch.setattr(timing, "dtw_cpu", lambda value: value)
    assert _whisper_dtw_cpu(Matrix()) == "matrix"
    assert operations == ["cpu", "double", "numpy"]
