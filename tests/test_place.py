from manga_babble.place import compute_bubble_candidates


def test_candidates_non_empty():
    frame = (0, 0, 1000, 1400)
    bodies = [(100, 600, 400, 1400), (600, 700, 950, 1400)]
    faces = [(150, 600, 300, 750), (680, 700, 820, 830)]
    cands = compute_bubble_candidates(frame, bodies, faces, top_k=3)
    assert len(cands) >= 1
    for c in cands:
        x1, y1, x2, y2 = c["bbox"]
        assert x2 > x1 and y2 > y1
        assert x1 >= 0 and y1 >= 0
