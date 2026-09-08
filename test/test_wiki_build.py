# -*- coding: utf-8 -*-
"""Tests for the standalone wiki HTML generator (scripts/build_wiki.py)."""

import os
import re

import pytest

from scripts.build_wiki import WIKI_CSS, WIKI_JS, build_wiki_html


@pytest.fixture(scope="session")
def wiki_html():
    return build_wiki_html()


def _card_id(kind, target):
    return ("group-" + target) if kind == "group" else (kind + "-card-" + target)


def bonus_card_ids(wiki_html):
    return re.findall(r'id="bonus-card-([a-z0-9_]+)"', wiki_html)


def test_html_is_generated(wiki_html):
    assert isinstance(wiki_html, str)
    assert len(wiki_html) > 100_000


def test_external_assets_referenced(wiki_html):
    assert '<link rel="stylesheet" href="wiki.css">' in wiki_html
    assert '<script src="wiki.js"></script>' in wiki_html


def test_external_asset_files_exist():
    for path in (WIKI_CSS, WIKI_JS):
        assert os.path.isfile(path), path
        with open(path, "r", encoding="utf-8") as fh:
            assert fh.read().strip()


@pytest.mark.parametrize(
    ("needle", "kind"),
    [
        (":root {", "css"),
        (".card.flash {", "css"),
        ("function setLang(lang) {", "js"),
        ("function routeFromHash() {", "js"),
    ],
)
def test_inline_mode_embeds_assets(needle, kind):
    html = build_wiki_html(inline=True)
    marker = "<style>" if kind == "css" else "<script>"
    assert marker in html
    assert needle in html


@pytest.mark.parametrize(
    "tab",
    ["tab-units", "tab-artifacts", "tab-events", "tab-countries", "tab-bonuses", "tab-rules"],
)
def test_all_tabs_present(wiki_html, tab):
    assert f'id="{tab}"' in wiki_html


@pytest.mark.parametrize(
    "needle",
    [
        "id=\"wiki-search\"",
        "id=\"lang-btn\"",
        "advanced_rules.pdf",
        "house_rules.pdf",
        "manual.pdf",
    ],
)
def test_header_and_rules_links_present(wiki_html, needle):
    assert needle in wiki_html


def test_localized_span_present(wiki_html):
    assert 'data-es="Mazo de Kharas"' in wiki_html


def test_all_links_resolve(wiki_html):
    links = set(re.findall(r'data-goto="([a-z-]+)/([a-z0-9_]+)"', wiki_html))
    ids = set(re.findall(r' id="([a-z-]+-[a-z0-9_]+)"', wiki_html))
    assert links, "no cross-links found"
    missing = sorted(_card_id(kind, t) for kind, t in links if _card_id(kind, t) not in ids)
    assert missing == []


@pytest.mark.parametrize(
    ("prefix", "minimum"),
    [
        ("<article class=\"card unit\"", 100),
        ("<article class=\"card artifact\"", 10),
        ("<article class=\"card event\"", 20),
        ("<article class=\"card country\"", 20),
        ("<article class=\"card bonus\"", 10),
        ("<div class=\"group\"", 1),
    ],
)
def test_card_counts_sane(wiki_html, prefix, minimum):
    assert wiki_html.count(prefix) >= minimum


@pytest.mark.parametrize(
    "bonus",
    ["tactical_rating", "combat_rating", "diplomacy", "revive", "healing",
     "emperor", "armor", "dragon_slayer", "dragon_orb", "gnome_tech"],
)
def test_bonus_cards_present(wiki_html, bonus):
    assert f'id="bonus-card-{bonus}"' in wiki_html


def _bonus_card_blocks(wiki_html):
    return re.findall(r'(<article class="card bonus".*?</article>)', wiki_html, flags=re.S)


def test_bonus_entries_explain_and_link_artifacts(wiki_html):
    cards = _bonus_card_blocks(wiki_html)
    assert cards, "no bonus cards found"
    assert len(cards) >= 10
    for card in cards:
        assert 'class="desc"' in card, "bonus card missing a description"
        assert 'data-goto="artifact/' in card, "bonus card does not link its artifacts"


def test_bonus_links_in_artifact_cards_resolve(wiki_html):
    others = re.findall(r'data-goto="bonus/([a-z0-9_]+)"', wiki_html)
    assert others, "no artifact card links to the Bonuses tab"
    ids = set(bonus_card_ids(wiki_html))
    assert all(key in ids for key in others)


def test_dragonflight_groups_present(wiki_html):
    for color in ("red", "blue", "green", "black", "white", "gold"):
        assert f'id="group-{color}"' in wiki_html


def _unit_card_blocks(wiki_html):
    return re.findall(r'(<article class="card unit".*?</article>)', wiki_html, flags=re.S)


def test_unit_movement_outside_meta_and_right_aligned(wiki_html):
    cards = _unit_card_blocks(wiki_html)
    assert cards, "no unit cards found"
    for card in cards:
        assert "Movement" not in re.search(r'<p class="meta">(.*?)</p>', card, flags=re.S).group(1)
    with_move = [c for c in cards if "stat-move" in c]
    assert with_move, "no unit card shows a right-aligned movement stat"
    for card in with_move:
        stat_row = re.search(r'<li class="stat-row">(.*?)</li>', card, flags=re.S)
        assert stat_row and "stat-move" in stat_row.group(1)


def test_unit_card_shows_only_one_rating(wiki_html):
    for card in _unit_card_blocks(wiki_html):
        assert card.count("l10n\" data-en=\"Combat\"") + card.count("l10n\" data-en=\"Tactical\"") <= 1


def test_counts_show_total_units_not_types(wiki_html):
    taman_group = re.search(
        r'id="group-taman".*?<span class="count">(\d+)</span>',
        wiki_html, flags=re.S)
    assert taman_group, "Taman Busuk group header not found"
    assert taman_group.group(1) == "10", "group header must sum unit quantities (2 cavalry + 8 infantry)"

    taman_card = re.search(
        r'(<article class="card country" id="country-card-taman".*?</article>)',
        wiki_html, flags=re.S)
    assert taman_card, "Taman Busuk country card not found"
    assert "Units</span> (10):" in taman_card.group(1)


def _event_adds_units(wiki_html, eid):
    m = re.search(r'id="event-card-%s".*?</article>' % re.escape(eid), wiki_html, flags=re.S)
    assert m, f"event card {eid} not found"
    return re.findall(r'data-goto="unit/([a-z0-9_]+)"', m.group(0))


def test_wizard_events_filtered_by_allegiance(wiki_html):
    ws = _event_adds_units(wiki_html, "ws_wizard")
    hl = _event_adds_units(wiki_html, "hl_wizard")
    assert sorted(ws) == ["fizban", "justarius", "par_salian"]
    assert sorted(hl) == ["dracart", "iolanthe", "ladonna"]