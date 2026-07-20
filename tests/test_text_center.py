from PIL import Image

from manga_babble.text.layout_text import draw_text_on_bubbles


def test_draw_runs_without_error():
    bubbles = [
        {
            "text": "ああ　いい",
            "order": 0,
            "bubble_bbox": [100, 100, 300, 400],
            "meta": {},
        }
    ]
    img = draw_text_on_bubbles(500, 600, bubbles, options={"genre": "default"})
    assert img.size == (500, 600)
    # Has some non-transparent pixels
    extrema = img.getextrema()
    assert extrema[3][1] > 0  # alpha channel has ink
