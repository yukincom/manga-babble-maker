"""#28 face hard-avoid + #29 multi-speaker face matching."""

from manga_babble.place.layout import build_layout, _match_face, _overlaps


def _det_faces_right_top():
    """Frame with face only in top-right — slot0 would land on it."""
    return {
        "schema_version": 1,
        "page": {"width": 1000, "height": 800},
        "detections": {
            "frames": [{"id": "f0", "bbox": [0, 0, 1000, 800], "score": 1}],
            "faces": [
                {"id": "face_tr", "bbox": [700, 50, 900, 250], "frame_id": "f0"},
            ],
            "bodies": [],
            "texts": [],
        },
    }


def test_bubble_avoids_face_hard():
    det = _det_faces_right_top()
    lines = {
        "schema_version": 1,
        "lines": [
            {
                "id": "a",
                "text": "たまにはツイッター…",
                "order": 0,
                "panel_index": 1,
                "type": "normal",
            },
        ],
    }
    lay = build_layout(det, lines)
    b = lay["bubbles"][0]
    face = det["detections"]["faces"][0]["bbox"]
    assert not _overlaps(tuple(b["bubble_bbox"]), tuple(face), pad=2.0)
    assert b["meta"].get("overlap_face") is False
    assert b["meta"].get("placement_mode") in (
        "slot",
        "free_space",
        "fallback_faces_only",
    )


def test_second_line_no_lone_face_tail():
    """Single face in panel: only first line gets it (#29)."""
    det = _det_faces_right_top()
    lines = {
        "schema_version": 1,
        "lines": [
            {"id": "a", "text": "右", "order": 0, "panel_index": 1, "type": "normal"},
            {"id": "b", "text": "左のセリフ", "order": 1, "panel_index": 1, "type": "normal"},
        ],
    }
    lay = build_layout(det, lines)
    assert lay["bubbles"][0]["speaker_face_id"] == "face_tr"
    assert lay["bubbles"][1]["speaker_face_id"] is None


def test_two_faces_rtl_assignment():
    det = {
        "schema_version": 1,
        "page": {"width": 1000, "height": 800},
        "detections": {
            "frames": [{"id": "f0", "bbox": [0, 0, 1000, 800], "score": 1}],
            "faces": [
                {"id": "left", "bbox": [100, 200, 200, 300], "frame_id": "f0"},
                {"id": "right", "bbox": [700, 200, 800, 300], "frame_id": "f0"},
            ],
            "bodies": [],
            "texts": [],
        },
    }
    lines = {
        "schema_version": 1,
        "lines": [
            {"id": "a", "text": "右の人", "order": 0, "panel_index": 1, "type": "normal"},
            {"id": "b", "text": "左の人", "order": 1, "panel_index": 1, "type": "normal"},
        ],
    }
    lay = build_layout(det, lines)
    # Prefer nearest-to-bubble after place; first (right slot) → right face
    assert lay["bubbles"][0]["speaker_face_id"] == "right"
    assert lay["bubbles"][1]["speaker_face_id"] == "left"


def test_body_clipped_does_not_block_entire_panel():
    """Spanning body mostly outside frame should not force face overlap."""
    det = {
        "schema_version": 1,
        "page": {"width": 1000, "height": 1000},
        "detections": {
            "frames": [{"id": "f0", "bbox": [0, 400, 1000, 800], "score": 1}],
            "faces": [
                {"id": "f", "bbox": [750, 500, 900, 650], "frame_id": "f0"},
            ],
            # Tall body from above frame into panel
            "bodies": [
                {"id": "b0", "bbox": [50, 0, 350, 900], "frame_id": "f0", "score": 0.9},
            ],
            "texts": [],
        },
    }
    lines = {
        "schema_version": 1,
        "lines": [
            {
                "id": "a",
                "text": "テストセリフです",
                "order": 0,
                "panel_index": 1,
                "type": "normal",
            },
        ],
    }
    lay = build_layout(det, lines)
    face = det["detections"]["faces"][0]["bbox"]
    assert not _overlaps(tuple(lay["bubbles"][0]["bubble_bbox"]), tuple(face), pad=2.0)


def test_match_face_slot_index_alone():
    faces = [{"id": "only", "bbox": [10, 10, 50, 50], "frame_id": "f0"}]
    frame = (0, 0, 200, 200)
    f0, _ = _match_face({"speaker": "A"}, faces, frame, "f0", slot_index=0)
    f1, bb1 = _match_face({"speaker": "A"}, faces, frame, "f0", slot_index=1)
    assert f0 is not None and f0["id"] == "only"
    assert f1 is None and bb1 is None
