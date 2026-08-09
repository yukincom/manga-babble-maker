"""Color ネーム: line art for detect, chromatic fill for occupy."""

import numpy as np

from manga_babble.place.occupancy import (
    extract_line_art_bgr,
    extract_person_fill_mask,
    page_has_color_fill,
    build_occupancy_color,
    hits_occupancy,
    region_ink_fraction,
)


def _make_pink_name(h=200, w=200):
    """White paper, black panel, pink person blob, black face dots."""
    # BGR
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # panel
    cv2 = __import__("cv2")
    cv2.rectangle(img, (10, 10), (190, 190), (0, 0, 0), 2)
    # pink fill body (BGR: pink ~ 221,207,255)
    img[40:160, 50:120] = (221, 207, 255)
    # black outline on person
    cv2.rectangle(img, (50, 40), (120, 160), (0, 0, 0), 2)
    # white free corner inside panel (right side)
    img[40:100, 140:180] = 255
    return img


def test_detects_color_fill():
    img = _make_pink_name()
    assert page_has_color_fill(img)


def test_line_art_is_bw():
    img = _make_pink_name()
    lines = extract_line_art_bgr(img)
    # pink gone → white or black only
    u = {tuple(p) for p in lines.reshape(-1, 3)[::50]}
    assert all(c[0] == c[1] == c[2] and c[0] in (0, 255) for c in u)


def test_fill_mask_marks_pink_not_white_corner():
    img = _make_pink_name()
    fill = extract_person_fill_mask(img, dilate_iter=1)
    # inside pink body
    assert fill[100, 80] > 0
    # white free corner
    assert fill[70, 160] == 0


def test_occupancy_uses_fill_not_whole_box():
    img = _make_pink_name()
    fill = extract_person_fill_mask(img)
    # #40: no line_ink — fill + face only
    occ = build_occupancy_color(
        fill, face_bboxes=[(55, 45, 90, 80)], include_lines=False
    )
    free = (140, 40, 180, 100)
    assert region_ink_fraction(occ, free) < 0.15
    assert not hits_occupancy(occ, free, max_frac=0.15)
    on_pink = (60, 80, 100, 140)
    assert hits_occupancy(occ, on_pink, max_frac=0.15)


def test_black_flat_background_is_not_hard():
    """Night-sky style black flat must stay free (#40). Only chroma fill is HARD."""
    import cv2

    h, w = 200, 200
    img = np.zeros((h, w, 3), dtype=np.uint8)  # black flat sky
    # pink person blob
    img[40:160, 30:90] = (221, 207, 255)
    cv2.rectangle(img, (10, 10), (190, 190), (0, 0, 0), 2)
    fill = extract_person_fill_mask(img, dilate_iter=1)
    occ = build_occupancy_color(
        fill,
        face_bboxes=[(40, 50, 80, 90)],
        frame_bboxes=[(10, 10, 190, 190)],
        include_lines=False,
    )
    # black sky on the right — free
    sky = (120, 40, 180, 100)
    assert region_ink_fraction(occ, sky) < 0.12
    assert not hits_occupancy(occ, sky, max_frac=0.12)
    # pink still hard
    assert hits_occupancy(occ, (45, 70, 75, 130), max_frac=0.12)
