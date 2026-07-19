from manga_babble.tone import resolve_tone


def test_explicit_type():
    tone, src = resolve_tone({"text": "hello", "type": "shout"})
    assert tone == "shout"
    assert src == "explicit"


def test_rule_thought_parens():
    tone, src = resolve_tone({"text": "（……そうか）"})
    assert tone == "thought"
    assert src == "rule"


def test_rule_shout():
    tone, src = resolve_tone({"text": "なんだと！？"})
    # has bang → shout
    assert tone == "shout"
    assert src == "rule"


def test_default():
    tone, src = resolve_tone({"text": "今日はいい天気だね"})
    assert tone == "normal"
    assert src == "default"
