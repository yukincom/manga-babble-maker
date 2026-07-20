"""Ink occupancy: white-inside-loose-body stays free; person bulk blocked."""

import numpy as np

from manga_babble.place.occupancy import (
    build_ink_mask,
    build_page_occupancy,
    hits_occupancy,
    region_ink_fraction,
)


def test_ink_mask_marks_dark_not_white():
    gray = np.full((100, 100), 255, dtype=np.uint8)
    gray[40:60, 40:60] = 0
    ink = build_ink_mask(gray, threshold=200, dilate_iter=0)
    assert ink[50, 50] == 255
    assert ink[10, 10] == 0


def test_white_corner_of_loose_body_is_free():
    """Large body AABB with ink only on left — right corner free (user diagram)."""
    gray = np.full((200, 200), 255, dtype=np.uint8)
    # vertical stick on left
    gray[20:180, 40:55] = 20
    gray[20:40, 35:60] = 20  # head blob
    body = (20, 15, 190, 190)
    face = (35, 20, 60, 45)
    occ = build_page_occupancy(
        gray, [face], body_bboxes=[body], frame_bboxes=[(0, 0, 200, 200)]
    )
    free_corner = (140, 40, 180, 80)
    assert region_ink_fraction(occ, free_corner) < 0.08
    assert not hits_occupancy(occ, free_corner, max_frac=0.08)
    on_person = (38, 80, 52, 120)
    assert hits_occupancy(occ, on_person, max_frac=0.08)


def test_envelope_blocks_near_ink_not_whole_page():
    gray = np.full((120, 120), 255, dtype=np.uint8)
    gray[50:70, 50:55] = 0
    occ = build_page_occupancy(gray, face_bboxes=None, body_bboxes=None)
    # far corner free
    assert not hits_occupancy(occ, (5, 5, 20, 20), max_frac=0.08)
    # on the stroke blocked
    assert hits_occupancy(occ, (48, 52, 58, 68), max_frac=0.08)


def test_face_pad_blocks_near_face():
    gray = np.full((100, 100), 255, dtype=np.uint8)
    face = (40, 40, 60, 60)
    occ = build_page_occupancy(gray, [face], face_pad_ratio=0.2)
    near = (36, 36, 42, 42)
    assert hits_occupancy(occ, near, max_frac=0.06)
