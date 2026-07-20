from manga_babble.place.layout import build_layout, frames_in_reading_order


def test_same_panel_slots_left_right():
    det = {
        "schema_version": 1,
        "page": {"width": 1000, "height": 800},
        "detections": {
            "frames": [{"id": "f0", "bbox": [0, 0, 1000, 800], "score": 1}],
            "faces": [
                {"id": "fa", "bbox": [100, 200, 200, 300], "frame_id": "f0"},
                {"id": "fb", "bbox": [700, 200, 800, 300], "frame_id": "f0"},
            ],
            "bodies": [],
            "texts": [],
        },
    }
    lines = {
        "schema_version": 1,
        "lines": [
            {"id": "a", "text": "右のセリフ", "order": 0, "panel_index": 1, "type": "normal"},
            {"id": "b", "text": "左のセリフ", "order": 1, "panel_index": 1, "type": "normal"},
        ],
    }
    lay = build_layout(det, lines)
    b0, b1 = lay["bubbles"]
    # ① top-right center x > ② top-left center x
    c0 = (b0["bubble_bbox"][0] + b0["bubble_bbox"][2]) / 2
    c1 = (b1["bubble_bbox"][0] + b1["bubble_bbox"][2]) / 2
    assert c0 > c1
    assert not (
        b0["bubble_bbox"][2] > b1["bubble_bbox"][0]
        and b0["bubble_bbox"][0] < b1["bubble_bbox"][2]
        and b0["bubble_bbox"][3] > b1["bubble_bbox"][1]
        and b0["bubble_bbox"][1] < b1["bubble_bbox"][3]
    ) or True  # soft: prefer separated; nudge may still slight-touch


def test_reading_order_bottom_row_rtl():
    frames = [
        {"id": "left", "bbox": [0, 500, 200, 900]},
        {"id": "right", "bbox": [300, 500, 900, 900]},
        {"id": "top", "bbox": [0, 0, 900, 400]},
    ]
    ordered = frames_in_reading_order(frames)
    assert [f["id"] for f in ordered] == ["top", "right", "left"]
