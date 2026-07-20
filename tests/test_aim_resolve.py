"""#36 AimRef: faces ∪ anchors, speaker match, no cross-panel pull."""

from manga_babble.place.aim import collect_aims, resolve_aim
from manga_babble.place.layout import build_layout, _overlaps


def test_collect_merges_faces_and_anchors():
    faces = [{"id": "f0", "bbox": [10, 10, 40, 40], "speaker": "A"}]
    anchors = [{"id": "a0", "bbox": [100, 100, 140, 140], "speaker": "B"}]
    aims = collect_aims(faces, anchors)
    assert len(aims) == 2
    assert {a.source for a in aims} == {"face", "anchor"}


def test_speaker_match_prefers_named_anchor():
    aims = collect_aims(
        [],
        [
            {"id": "a_right", "bbox": [700, 200, 800, 300], "speaker": "話者A", "frame_id": "f0"},
            {"id": "a_left", "bbox": [100, 200, 200, 300], "speaker": "話者B", "frame_id": "f0"},
        ],
    )
    frame = (0.0, 0.0, 1000.0, 800.0)
    aim, bb, src = resolve_aim(
        {"speaker": "話者B", "text": "左"},
        aims,
        frame,
        "f0",
        slot_index=0,
    )
    assert aim is not None
    assert aim.id == "a_left"
    assert src == "anchor"
    assert bb[0] < 300


def test_explicit_anchor_id():
    aims = collect_aims(
        [],
        [
            {"id": "a1", "bbox": [10, 10, 50, 50], "speaker": "X"},
            {"id": "a2", "bbox": [200, 10, 250, 50], "speaker": "Y"},
        ],
    )
    frame = (0.0, 0.0, 400.0, 200.0)
    aim, _, _ = resolve_aim(
        {"anchor_id": "a2", "speaker": "X"},
        aims,
        frame,
        None,
        slot_index=0,
    )
    assert aim is not None and aim.id == "a2"


def test_single_aim_second_line_no_reuse():
    aims = collect_aims(
        [{"id": "only", "bbox": [50, 50, 100, 100], "frame_id": "f0"}],
        [],
    )
    frame = (0.0, 0.0, 400.0, 400.0)
    a0, _, _ = resolve_aim({"text": "a"}, aims, frame, "f0", slot_index=0)
    a1, bb1, src1 = resolve_aim(
        {"text": "b"},
        aims,
        frame,
        "f0",
        slot_index=1,
        bodies=[{"id": "b0", "bbox": [20, 40, 120, 300], "frame_id": "f0"}],
        allow_body_fallback=True,
    )
    assert a0 is not None and a0.id == "only"
    assert src1 == "body"
    assert a1 is not None and a1.id == "body_aim"


def test_structure_layout_speaker_split_no_image():
    """Mode B: structure JSON only — speaker A right, B left."""
    structure = {
        "schema_version": 1,
        "page": {"width": 1000, "height": 800},
        "frames": [{"id": "f0", "bbox": [40, 40, 960, 760]}],
        "anchors": [
            {
                "id": "a_right",
                "bbox": [680, 220, 820, 380],
                "speaker": "話者A",
                "frame_id": "f0",
            },
            {
                "id": "a_left",
                "bbox": [160, 240, 300, 400],
                "speaker": "話者B",
                "frame_id": "f0",
            },
        ],
        "faces": [],
        "bodies": [],
        "lines": [
            {
                "id": "l0",
                "text": "右から話すよ",
                "order": 0,
                "speaker": "話者A",
                "panel_index": 1,
                "type": "normal",
            },
            {
                "id": "l1",
                "text": "左のセリフだ",
                "order": 1,
                "speaker": "話者B",
                "panel_index": 1,
                "type": "normal",
            },
        ],
    }
    # Combined doc as both det and lines
    lay = build_layout(structure, structure)
    assert len(lay["bubbles"]) == 2
    b0, b1 = lay["bubbles"]
    assert b0["speaker_face_id"] == "a_right"
    assert b1["speaker_face_id"] == "a_left"
    # Hard-avoid: bubbles should not cover their aim heads
    assert not _overlaps(tuple(b0["bubble_bbox"]), tuple(b0["speaker_face_bbox"]), pad=2)
    assert not _overlaps(tuple(b1["bubble_bbox"]), tuple(b1["speaker_face_bbox"]), pad=2)
    # Roughly correct halves
    c0 = (b0["bubble_bbox"][0] + b0["bubble_bbox"][2]) / 2
    c1 = (b1["bubble_bbox"][0] + b1["bubble_bbox"][2]) / 2
    assert c0 > c1


def test_no_cross_panel_speaker_pull():
    aims = collect_aims(
        [
            {
                "id": "other_panel",
                "bbox": [10, 10, 50, 50],
                "speaker": "話者A",
                "frame_id": "f_other",
            }
        ],
        [],
    )
    # Current frame has no aims; speaker A only exists in other panel
    frame = (0.0, 100.0, 400.0, 400.0)
    aim, bb, _ = resolve_aim(
        {"speaker": "話者A", "text": "x"},
        aims,
        frame,
        "f_here",
        slot_index=0,
        allow_body_fallback=False,
    )
    # Center of other face is not in frame → pool empty → null
    assert aim is None and bb is None
