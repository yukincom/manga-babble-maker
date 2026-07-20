from manga_babble.shapes.templates import list_templates, load_template, pick_template_path


def test_list_fun_cloud_templates():
    paths = list_templates("fun-cloud")
    assert len(paths) >= 6
    assert "fun-cloud" in paths[0].name


def test_pick_and_load():
    p = pick_template_path("fun-cloud", seed=0)
    assert p is not None
    im = load_template(str(p))
    assert im.mode == "RGBA"
    assert im.size[0] > 0


def test_jagged_templates():
    paths = list_templates("jagged")
    assert len(paths) >= 5
