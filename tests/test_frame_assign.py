from manga_babble.detect.rtdetr_onnx import (
    _assign_frame_by_face_rule,
    _link_bodies_to_face_frames,
)


def test_face_center_prefers_main_panel_not_edge_clip():
    """Face mostly in upper panel; only edge would touch lower — center wins."""
    frames = [
        {"id": "upper", "bbox": [0, 0, 100, 100]},
        {"id": "lower", "bbox": [0, 100, 100, 200]},
    ]
    # face center at y=40 → upper
    face = {"bbox": [40, 20, 60, 60]}
    assert _assign_frame_by_face_rule(face, frames) == "upper"


def test_span_body_links_to_face_frame():
    frames = [
        {"id": "upper", "bbox": [0, 0, 200, 100]},
        {"id": "lower", "bbox": [0, 100, 200, 300]},
    ]
    faces = [
        {"id": "face0", "bbox": [80, 30, 120, 70], "frame_id": "upper"},
    ]
    # body spans both panels
    bodies = [
        {"id": "b0", "bbox": [70, 20, 130, 280]},
    ]
    _assign = _assign_frame_by_face_rule(bodies[0], frames)
    bodies[0]["frame_id"] = _assign
    _link_bodies_to_face_frames(bodies, faces, frames)
    assert bodies[0]["frame_id"] == "upper"
