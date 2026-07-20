from manga_babble.text.breaks import split_text_to_chunks
from manga_babble.text.profile import resolve_break_profile


def test_explicit_fullwidth_space():
    assert split_text_to_chunks("たまには　ツイッター…") == ["たまには", "ツイッター…"]


def test_explicit_slash():
    assert split_text_to_chunks("たまには/ツイッター…") == ["たまには", "ツイッター…"]


def test_explicit_nandakore():
    assert split_text_to_chunks("なんだ　これ") == ["なんだ", "これ"]


def test_no_shred_particles():
    chunks = split_text_to_chunks("たまにはツイッター…")
    assert "に" not in chunks and "は" not in chunks


def test_no_shred_nanda():
    chunks = split_text_to_chunks("なんだこれ")
    assert "な" not in chunks


def test_margin_short():
    chunks = split_text_to_chunks(
        "※短い注釈", line_meta={"placement": "page_margin"}
    )
    assert len(chunks) == 1


def test_profile_speakers_generic():
    p = resolve_break_profile(
        {"genre": "mixed", "speakers": {"話者A": {"voice": "dense"}}},
        speaker="話者A",
    )
    assert p.voice == "dense"


def test_long_vowel_not_orphan_column():
    """#27: だー！ must not become ['…だ', 'ー！']."""
    chunks = split_text_to_chunks("やっと正月だー！")
    assert not any(c.startswith("ー") for c in chunks)
    assert any("だー" in c or "だー！" in c for c in chunks)


def test_twitter_long_vowel_stays_in_word():
    chunks = split_text_to_chunks("たまにはツイッター…")
    joined = "".join(chunks)
    assert "ツイッター" in joined
    # ー should not be its own chunk
    assert "ー" not in chunks
