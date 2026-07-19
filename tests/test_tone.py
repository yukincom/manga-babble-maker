from manga_babble.tone import resolve_tone


def test_explicit_type():
    tone, src = resolve_tone({"text": "hello", "type": "shout"})
    assert tone == "shout"
    assert src == "explicit"


def test_rule_thought_parens():
    tone, src = resolve_tone({"text": "（……そうか）"})
    assert tone == "thought"
    assert src == "rule"


def test_rule_shout_double_bang():
    tone, src = resolve_tone({"text": "ふざけるな！！"})
    assert tone == "shout"
    assert src == "rule"


def test_single_bang_stays_normal():
    tone, src = resolve_tone({"text": "なんだと！？"})
    # single ！ → not shout (soft)
    assert tone == "normal"
    assert src == "default"


def test_note_margin():
    from manga_babble.tone.resolve import is_page_margin_line

    line = {"text": "※ロゴは実際のものと異なります"}
    assert is_page_margin_line(line)
    tone, src = resolve_tone(line)
    assert tone == "narration"


def test_default():
    tone, src = resolve_tone({"text": "今日はいい天気だね"})
    assert tone == "normal"
    assert src == "default"
