"""Batches respect Gemini's inline payload limit (~20 MB per request)."""

from types import SimpleNamespace

from bondy.core.images import MAX_IMAGE_BYTES
from bondy.core.semantic import MAX_BATCH_BYTES, make_batches


def _group(n_bytes: int):
    return SimpleNamespace(image=SimpleNamespace(data=b"\0" * n_bytes))


def test_caps_stay_below_the_provider_limit():
    assert MAX_IMAGE_BYTES <= MAX_BATCH_BYTES < 20 * 1024 * 1024


def test_batches_split_by_total_bytes_even_under_batch_size():
    mb = 1024 * 1024
    groups = [_group(7 * mb) for _ in range(5)]
    batches = make_batches(groups, batch_size=8)
    assert [len(b) for b in batches] == [2, 2, 1]  # 14 MB, 14 MB, 7 MB
    assert all(sum(len(g.image.data) for g in b) <= MAX_BATCH_BYTES for b in batches)


def test_an_oversized_single_image_still_gets_its_own_batch():
    groups = [_group(MAX_BATCH_BYTES + 1), _group(10)]
    assert [len(b) for b in make_batches(groups, batch_size=8)] == [1, 1]
