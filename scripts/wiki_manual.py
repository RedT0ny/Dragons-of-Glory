# -*- coding: utf-8 -*-
"""
Structural schema for the wiki Rules-tab manual.

This module only describes WHAT the manual contains (sections, subsections,
block order and block types). Every human-readable string lives in the game's
locale files - data/locale/en.yaml and data/locale/es.yaml - under the top-level
``manual:`` namespace, and is fetched through the same localization machinery
WikiGen uses for country, unit, artifact and event names (see ``_manual_locale``
in scripts/build_wiki.py).

Word order rule
---------------
Each section title and subsection title are read from ``manual.<id>.title`` and
``manual.<id>.<sub>.title``. The subsection body blocks are read from
``manual.<id>.<sub>.<key>`` inside the locale files, where ``key`` is one of:

    p1, p2, ...   paragraph text (one string)
    bullets       bullet list (a YAML list of strings)
    steps         numbered list (a YAML list of strings)
    warn          callout: {"title": str, "text": str}
    table         table: {"headers": [str], "rows": [[str, ...], ...]}
    crt           the CRT grid, generated from the game's own data/crt.csv
                  (no locale key; language-neutral except the localized
                  "Roll"/"Tirada" header)
    calendar      the campaign calendar, generated from data/calendar.csv
                  (winter rows are highlighted; no locale key)
    align         the country alignment table, generated from data/countries.yaml
                  (country names resolve through the localize machinery; hint
                  columns are localized; no locale key)

Inline cross-links use the marker  [[kind:id]]  (e.g. [[artifact:dragonlance]],
[[country:qualinesti]], [[event:ws_diplomacy]]). The link label is resolved
automatically from the already-localized names in the locale files, so the text
itself never carries a display label.
"""

MANUAL_SECTIONS = [
    {
        "id": "overview",
        "subsections": {
            "what_is": [
                {"t": "p", "key": "p1"},
                {"t": "p", "key": "p2"},
                {"t": "ul", "key": "bullets"},
            ],
            "how_to_read": [
                {"t": "p", "key": "p1"},
                {"t": "p", "key": "p2"},
                {"t": "warn", "key": "warn"},
            ],
        },
    },
    {
        "id": "turn",
        "subsections": {
            "phases": [
                {"t": "p", "key": "p1"},
                {"t": "ol", "key": "steps"},
                {"t": "warn", "key": "warn"},
            ],
            "calendar": [
                {"t": "p", "key": "p1"},
                {"t": "calendar"},
            ],
            "initiative": [
                {"t": "p", "key": "p1"},
                {"t": "ul", "key": "bullets"},
            ],
            "replacements": [
                {"t": "p", "key": "p1"},
                {"t": "p", "key": "p2"},
                {"t": "p", "key": "p3"},
                {"t": "p", "key": "p4"},
                {"t": "p", "key": "p5"},
            ],
        },
    },
    {
        "id": "countries",
        "subsections": {
            "powers": [
                {"t": "p", "key": "p1"},
                {"t": "ul", "key": "bullets"},
                {"t": "align"},
            ],
            "activation": [
                {"t": "p", "key": "p1"},
                {"t": "p", "key": "p2"},
            ],
            "conquest": [
                {"t": "p", "key": "p1"},
                {"t": "p", "key": "p2"},
                {"t": "warn", "key": "warn"},
            ],
        },
    },
    {
        "id": "units",
        "subsections": {
            "types": [
                {"t": "p", "key": "p1"},
                {"t": "ul", "key": "bullets"},
            ],
            "ratings": [
                {"t": "p", "key": "p1"},
                {"t": "p", "key": "p2"},
            ],
            "statuses": [
                {"t": "ul", "key": "bullets"},
                {"t": "warn", "key": "warn"},
            ],
        },
    },
    {
        "id": "movement",
        "subsections": {
            "movement_points": [
                {"t": "p", "key": "p1"},
                {"t": "ul", "key": "bullets"},
            ],
            "transport": [
                {"t": "p", "key": "p1"},
                {"t": "p", "key": "p2"},
            ],
        },
    },
    {
        "id": "combat",
        "subsections": {
            "land_combat": [
                {"t": "p", "key": "p1"},
                {"t": "ul", "key": "bullets"},
            ],
            "crt": [
                {"t": "p", "key": "p1"},
                {"t": "crt"},
                {"t": "tbl", "key": "table"},
                {"t": "p", "key": "p2"},
            ],
            "dragon_combat": [
                {"t": "p", "key": "p1"},
                {"t": "p", "key": "p2"},
            ],
            "naval_combat": [
                {"t": "p", "key": "p1"},
            ],
            "siege": [
                {"t": "p", "key": "p1"},
                {"t": "p", "key": "p2"},
            ],
        },
    },
    {
        "id": "winter",
        "subsections": {
            "winter": [
                {"t": "p", "key": "p1"},
                {"t": "ul", "key": "bullets"},
            ],
            "supply": [
                {"t": "p", "key": "p1"},
                {"t": "ul", "key": "bullets"},
            ],
        },
    },
    {
        "id": "naval",
        "subsections": {
            "interception": [
                {"t": "p", "key": "p1"},
                {"t": "ul", "key": "bullets"},
            ],
            "invasion": [
                {"t": "p", "key": "p1"},
            ],
        },
    },
    {
        "id": "artifacts",
        "subsections": {
            "artifacts": [
                {"t": "p", "key": "p1"},
                {"t": "tbl", "key": "table"},
            ],
            "heroes": [
                {"t": "p", "key": "p1"},
                {"t": "warn", "key": "warn"},
            ],
        },
    },
    {
        "id": "events",
        "subsections": {
            "how_they_work": [
                {"t": "p", "key": "p1"},
                {"t": "ul", "key": "bullets"},
                {"t": "p", "key": "p2"},
            ],
        },
    },
    {
        "id": "victory",
        "subsections": {
            "victory": [
                {"t": "p", "key": "p1"},
                {"t": "p", "key": "p2"},
            ],
        },
    },
    {
        "id": "options",
        "subsections": {
            "options": [
                {"t": "p", "key": "p1"},
                {"t": "tbl", "key": "table"},
            ],
        },
    },
    {
        "id": "scenarios",
        "subsections": {
            "scenarios": [
                {"t": "p", "key": "p1"},
                {"t": "ul", "key": "bullets"},
            ],
        },
    },
]