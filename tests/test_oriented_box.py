from core.oriented_box import bbox_to_quad, normalize_quad, normalized_quad_coords
from core.unified import BBox


def test_normalize_quad_orders_top_left_first():
    pts = [(90, 70), (20, 80), (10, 20), (80, 10)]
    quad = normalize_quad(pts)
    assert quad is not None
    assert quad[0] == (10.0, 20.0)
    assert len(quad) == 4


def test_bbox_to_quad_and_normalized_coords_clamp():
    quad = bbox_to_quad(BBox(-10, 10, 120, 90))
    quad = normalize_quad(quad, image_width=100, image_height=80, clamp=True)
    assert quad is not None
    coords = normalized_quad_coords(quad, 100, 80)
    assert len(coords) == 8
    assert all(0.0 <= v <= 1.0 for v in coords)
