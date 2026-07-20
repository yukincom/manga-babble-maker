from manga_babble.script_parse import parse_script


def test_parse_basic():
    text = """
page1
[1]
小雪 "やっと正月だー！" giza
ナレーション "2025年" narration
[2]
小雪 "A" normal
小雪 "B" normal
[枠外]
※注釈です
"""
    doc = parse_script(text)
    assert doc["page"]["id"] == "page1"
    assert len(doc["lines"]) == 5
    assert doc["lines"][0]["panel_index"] == 1
    assert doc["lines"][0]["type"] == "giza"
    assert doc["lines"][1]["type"] == "narration"
    assert doc["lines"][2]["panel_index"] == 2
    assert doc["lines"][4]["meta"]["placement"] == "page_margin"


def test_zenkaku_panel():
    doc = parse_script('[１]\n小雪 "あ" normal\n')
    assert doc["lines"][0]["panel_index"] == 1
