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


def test_panel_margin_combined():
    doc = parse_script(
        '[4]\n小雪 "見慣れぬアイコン・・・" normal\n[4][枠外]\n※ロゴは実際のものと異なります\n'
    )
    assert doc["lines"][0]["panel_index"] == 4
    assert doc["lines"][1]["meta"]["placement"] == "page_margin"
    assert doc["lines"][1]["text"].startswith("※")


def test_fun_cloud_and_shout():
    doc = parse_script(
        '[１]\n小雪 "やっと正月だー！" fun-cloud\n[3]\n小雪 "なんだこれ" shout\n'
    )
    assert doc["lines"][0]["type"] == "fun-cloud"
    assert doc["lines"][1]["type"] == "shout"
    assert doc["lines"][1]["panel_index"] == 3
