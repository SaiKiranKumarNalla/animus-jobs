from jobagent import autofilter, categories, config, packs, scoring, verifier


def test_fresh_install_uses_generic_pack_without_placeholders():
    assert config.get_settings()["setup_done"] is False
    lanes = packs.radar_lanes()
    assert lanes and all("{" not in brief for _, _, brief in lanes)


def test_builtin_packs_load_and_fill():
    for b in packs.builtins():
        pk = {**packs.GENERIC, **packs.builtin(b["id"])}
        assert pk["lanes"], b["id"]
        assert all("{" not in brief for _, _, brief in packs.radar_lanes(pk))


def test_french_titles_translate_and_tag():
    t = scoring.translate_fr("Directeur scientifique (H/F) – Imagerie TEP")
    assert "chief scientific officer" in t and "pet" in t
    assert "exec" in categories.tag({"title": "CTO / cofondateur", "description": "", "kind": "job"})


def test_generic_links_by_kind():
    assert verifier.generic_for_kind("https://example.com/careers/", "job")[0]
    assert verifier.generic_for_kind("https://example.com/contact/", "job")[0]
    assert not verifier.generic_for_kind("https://example.com/careers/", "target")[0]
    assert not verifier.generic_for_kind("https://jobs.ashbyhq.com/acme/1234-abcd", "job")[0]
    assert verifier.generic_for_kind("https://grantoria.com/grants-for-researchers", "funding")[0]


def test_duplicate_titles():
    n = autofilter.norm_title
    assert autofilter._similar(n("Ingénieur R&D Imagerie (H/F)"), n("Ingénieur R&D imagerie H/F"))
    assert not autofilter._similar(n("MEDICA 2026"), n("MEDICA 2027"))
    assert not autofilter._similar(n("IET National Travel Award 2026"), n("IET International Travel Award 2026"))


def test_template_matcher_prefers_matching_titles():
    from jobagent import db, templates
    db.init()
    t = templates.add(title="CTO – Medical imaging AI startup", text="lead engineering, deep learning, PET/CT, MDR")
    f = templates.matcher()
    assert f({"title": "Co-founder & CTO - IA & Imagerie Médicale", "description": ""})[0] > \
        f({"title": "Senior Data Scientist", "description": ""})[0]
    templates.delete(t["id"])


def test_game_levels_and_quests():
    from jobagent import game
    assert game._level(0)[0] == 1 and game._level(100)[0] == 2 and game._level(299)[0] == 2 and game._level(300)[0] == 3
    q = game.quests([("2026-01-01", "swipe")] * 20, "2026-01-01")
    assert q[0]["done"] and not q[3]["done"]
    assert game.streak([("2026-01-01", "swipe"), ("2026-01-02", "swipe")], "2026-01-02") == 2
