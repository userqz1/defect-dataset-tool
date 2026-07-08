"""Unit tests for core.annotation_fix (out-of-bounds clamp + stray drop)."""
from core.annotation_fix import clamp_points, clamp_shapes
from core.models import Shape


def _rect(pts):
    return Shape(label="a", shape_type="rectangle", points=pts)


def test_clamp_overshoot():
    kept, clamped, removed = clamp_shapes([_rect([(-5, -5), (110, 120)])], 100, 100)
    assert (clamped, removed) == (1, 0)
    assert kept[0].points == [(0.0, 0.0), (100.0, 100.0)]


def test_drop_fully_outside():
    # Box entirely to the right of the image → collapses after clamp → dropped.
    kept, clamped, removed = clamp_shapes([_rect([(120, 10), (140, 30)])], 100, 100)
    assert (clamped, removed) == (0, 1)
    assert kept == []


def test_inbounds_untouched():
    s = _rect([(10, 10), (50, 50)])
    kept, clamped, removed = clamp_shapes([s], 100, 100)
    assert (clamped, removed) == (0, 0)
    assert kept == [s]


def test_zero_image_size_is_noop():
    s = _rect([(-5, -5), (110, 110)])
    kept, clamped, removed = clamp_shapes([s], 0, 0)
    assert kept == [s] and (clamped, removed) == (0, 0)


def test_point_repositioned_never_dropped():
    p = Shape(label="a", shape_type="point", points=[(150, 150)])
    kept, clamped, removed = clamp_shapes([p], 100, 100)
    assert removed == 0 and clamped == 1
    assert kept[0].points == [(100.0, 100.0)]


def test_mixed_batch_counts():
    shapes = [
        _rect([(10, 10), (40, 40)]),      # in-bounds
        _rect([(-5, 5), (30, 200)]),      # overshoot → clamp
        _rect([(300, 300), (320, 320)]),  # fully outside → drop
    ]
    kept, clamped, removed = clamp_shapes(shapes, 100, 100)
    assert (clamped, removed) == (1, 1)
    assert len(kept) == 2


def test_clamp_points_basic():
    assert clamp_points([(-1, 50), (200, 200)], 100, 120) == [
        (0.0, 50.0),
        (100.0, 120.0),
    ]
