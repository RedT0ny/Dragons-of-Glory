# -*- coding: utf-8 -*-
"""
Builds the HTML game wiki (assets/html/wiki.html).

The wiki shows the four game pillars - units, artifacts, events and countries -
in a single page with tabs, a client-side search box and cross-entry links.
A Rules tab links to the PDF manuals shipped in assets/doc (the same files
exposed by the in-game Help menu).

The styling and client-side behaviour live in the static sibling files
assets/html/wiki.css and assets/html/wiki.js, which are referenced from the
generated page. Pass --inline to embed both files into a single portable copy.

Usage:
    python scripts/build_wiki.py            # external wiki.css / wiki.js
    python scripts/build_wiki.py --inline   # self-contained single file

It depends only on PyYAML and the standard library, so it can run anywhere
(the game parsers are reimplemented here so this script does not need PySide6).
"""

import csv
import html
import os
import re
import sys
from collections import defaultdict

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.content.config import (
    IMAGES_DIR,
    DOC_DIR,
    WIKI_HTML,
    WIKI_CSS,
    WIKI_JS,
    HTML_DIR,
    EVENTS_DATA,
    ARTIFACTS_DATA,
    UNITS_DATA,
    COUNTRIES_DATA,
    CRT_DATA,
    CALENDAR_DATA,
    LOCALE_DIR,
)
from src.content.constants import DRAGONFLIGHTS

from wiki_manual import MANUAL_SECTIONS


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "item"


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


_MANUAL_LINK_RE = re.compile(r"\[\[([a-z_]+):([\w_-]+)\]\]")


# Ground movement cost by terrain (standard / winter), rendered with a terrain
# thumbnail from assets/img/<key>.png. Costs mirror src/game/map.py
# _get_ground_movement_cost: 1 point for open terrain, forest/jungle/glacier
# cost 2 (suffix "*" in the rendered table), mountains are only reachable
# through a pass/tunnel border and become impassable in winter when snow blocks
# the passes ("—" = impassable to ground troops).
TERRAIN_ROWS = (
    ("grassland", "1", "1"),
    ("steppe", "1", "1"),
    ("forest", "2*", "2*"),
    ("jungle", "2*", "2*"),
    ("glacier", "2*", "2*"),
    ("mountain", "—**", "—**"),
    ("ocean", "—", "—"),
    ("desert", "—", "—"),
    ("swamp", "—", "—"),
    ("maelstrom", "—", "—"),
)


def _load_locale(lang: str) -> dict:
    path = os.path.join(LOCALE_DIR, f"{lang}.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _read_text(path) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _get(node, *path, default=None):
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def load_countries() -> dict:
    with open(COUNTRIES_DATA, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    countries = {}
    for cid, info in sorted(raw.items()):
        countries[cid] = {
            "id": cid,
            "capital_id": info.get("capital_id"),
            "color": info.get("color"),
            "allegiance": info.get("allegiance", "neutral"),
            "strength": info.get("strength", 0),
            "alignment": [int(x) for x in (info.get("alignment") or [0, 0])],
            "tags": list(info.get("tags") or []),
            "locations": info.get("locations") or {},
            "territories": list(info.get("territories") or []),
        }
    return countries


def load_units() -> list:
    specs = []
    with open(UNITS_DATA, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            gv = lambda k: (row.get(k) or "").strip() or None
            gint = lambda k: int(row[k]) if (row.get(k) or "").isdigit() else None

            land = gv("land")
            dragonflight = land.lower() if land and land.lower() in DRAGONFLIGHTS else None
            country = None if dragonflight else land

            u_type = gv("type")
            race = gv("race")
            csv_id = gv("id")

            if csv_id:
                base_id = _slugify(csv_id)
            else:
                land_key = _slugify(land) if land else ""
                base_id = f"{land_key}_{race or 'r'}_{u_type or 'u'}"

            specs.append({
                "raw_id": base_id,
                "slug": _slugify(base_id),
                "named": bool(csv_id),
                "unit_type": u_type,
                "race": race,
                "country": country,
                "dragonflight": dragonflight,
                "allegiance": (gv("allegiance") or "") or None,
                "terrain_affinity": gv("terrain_affinity"),
                "combat_rating": gint("combat_rating"),
                "tactical_rating": gint("tactical_rating"),
                "movement": gint("movement"),
                "quantity": gint("quantity") or 1,
                "picture": gv("picture") or "army.jpg",
            })
    return specs


def load_artifacts() -> dict:
    with open(ARTIFACTS_DATA, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    artifacts = {}
    for aid, info in sorted(raw.items()):
        artifacts[aid] = {
            "id": aid,
            "type": info.get("type", "artifact"),
            "description": info.get("description", ""),
            "effect": info.get("effect", ""),
            "bonus": info.get("bonus", {}),
            "requirements": list(info.get("requirements") or []),
            "is_consumable": info.get("is_consumable", False),
            "picture": info.get("picture", "artifact.jpg"),
        }
    return artifacts


def load_events() -> dict:
    with open(EVENTS_DATA, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    events = {}
    for eid, info in sorted(raw.items()):
        events[eid] = {
            "id": eid,
            "type": info.get("type", "resource"),
            "description": info.get("description", ""),
            "turn": info.get("turn"),
            "requirements": list(info.get("requirements") or []),
            "effects": info.get("effects") or {},
            "allegiance": info.get("allegiance"),
            "max_occurrences": info.get("max_occurrences"),
            "picture": info.get("picture", "event.jpg"),
        }
    return events


class WikiGen:
    LOCATION_TYPES = {
        "city": ("City", "Ciudad"),
        "port": ("Port", "Puerto"),
        "fortress": ("Fortress", "Fortaleza"),
        "undercity": ("Undercity", "Ciudad subterránea"),
        "temple": ("Temple", "Templo"),
    }
    ALLEGIANCE_LABELS = {
        "neutral": ("Neutral", "Neutral"),
        "whitestone": ("Whitestone", "Piedra Blanca"),
        "highlord": ("Highlord", "Señor del Dragón"),
    }
    SECTION_LABELS = {
        "units": ("Units", "Unidades"),
        "artifacts": ("Artifacts", "Artefactos"),
        "events": ("Events", "Eventos"),
        "countries": ("Countries", "Naciones"),
        "bonuses": ("Bonuses", "Bonus"),
        "rules": ("Rules", "Reglas"),
    }
    EVENT_TYPE_LABELS = {
        "diplomacy": ("Diplomacy", "Diplomacia"),
        "artifact": ("Artifact", "Artefacto"),
        "resource": ("Resource", "Recurso"),
        "bonus": ("Bonus", "Bonificación"),
        "units": ("Units", "Unidades"),
    }
    ARTICLE_TYPE_LABELS = {
        "artifact": ("Artifact", "Artefacto"),
        "resource": ("Resource", "Recurso"),
    }
    ADD_UNITS_ALIASES = {
        "golden_general": ["laurana"],
        "good_dragons": [
            "gold_dragon_wing", "silver_dragon_wing", "bronze_dragon_wing",
            "copper_dragon_wing", "brass_dragon_wing",
        ],
    }
    # key -> (name_en, name_es, description_en, description_es). Order sets the
    # display order of the Bonuses tab. Missing/misc keys fall back to a generic
    # description when they appear in the data.
    BONUS_REFERENCE = [
        ("tactical_rating",
         "Tactical Rating", "Táctica",
         "Adds to (or multiplies) the equipped unit's Tactical Rating.",
         "Suma (o multiplica) la Táctica de la unidad equipada."),
        ("combat_rating",
         "Combat Rating", "Combate",
         "Adds to (or multiplies) the equipped unit's Combat Rating.",
         "Suma (o multiplica) el Combate de la unidad equipada."),
        ("diplomacy",
         "Diplomacy bonus", "Bonus diplomático",
         "Each owned artifact lists one or more countries; every matching artifact "
         "adds +1 to that country's activation roll.",
         "Cada artefacto propio indica una o más naciones; cada artefacto que "
         "coincida suma +1 a la tirada de activación de esa nación."),
        ("revive",
         "Revive", "Revivir",
         "Once per battle: if the equipped leader is destroyed, the artifact is "
         "destroyed instead and the leader revives.",
         "Una vez por batalla: si el líder equipado es destruido, el artefacto se "
         "destruye en su lugar y el líder revive."),
        ("healing",
         "Healing", "Curación",
         "Heals a depleted unit during combat. Consumable healing artifacts are "
         "destroyed in the process.",
         "Cura a una unidad agotada durante el combate. Los artefactos de curación "
         "consumibles se destruyen al usarlos."),
        ("emperor",
         "Emperor", "Emperador",
         "The equipped leader becomes an Emperor, able to command every dragonflight "
         "of their allegiance.",
         "El líder equipado se convierte en Emperador, capaz de comandar todos los "
         "alados de dragón de su bando."),
        ("armor",
         "Armor", "Armadura",
         "Sturdy armor: +1 to the leader's escape roll when fleeing combat.",
         "Armadura resistente: +1 a la tirada de huida del líder al escapar del combate."),
        ("dragon_slayer",
         "Dragon Slayer", "Mata Dragones",
         "Truly effective against dragons: negates the enemy's dragon combat bonus "
         "during combat.",
         "Realmente efectivo contra dragones: anula el bonus de combate de los "
         "dragones enemigos durante el combate."),
        ("dragon_orb",
         "Dragon Orb", "Orbe del Dragón",
         "Before combat against dragons or draconians, roll 1d6; if it is equal to or "
         "lower than the leader's Tactical Rating every opposing dragon unit is "
         "destroyed, otherwise the leader is destroyed. The orb is consumed either way.",
         "Antes del combate contra dragones o draconianos, tira 1d6; si es igual o "
         "menor que la Táctica del líder, todas las unidades de dragón enemigas quedan "
         "destruidas; si no, el líder es destruido. El orbe se consume en ambos casos."),
        ("gnome_tech",
         "Gnome Tech", "Tecnología Gnoma",
         "Before combat, roll 2d6. On any non-double result the side gains a combat "
         "die roll modifier equal to the highest die; on doubles the side suffers a "
         "−6 modifier and the device is destroyed.",
         "Antes del combate, tira 2d6. Si no salen dobles, el bando recibe un "
         "modificador de tirada de combate igual al dado más alto; si salen dobles, "
         "sufre un modificador de −6 y el dispositivo queda destruido."),
    ]
    GENERIC_BONUS = (
        "Special artifact bonus.", "Bonus especial de artefacto.")

    def __init__(self):
        self.en = _load_locale("en")
        self.es = _load_locale("es")
        self.countries = load_countries()
        self.units = load_units()
        self.artifacts = load_artifacts()
        self.events = load_events()

        self.units_by_id = {u["raw_id"]: u for u in self.units}
        self.units_by_type = defaultdict(list)
        self.units_by_race = defaultdict(list)
        self.units_by_land = defaultdict(list)
        for u in self.units:
            if u["unit_type"]:
                self.units_by_type[u["unit_type"]].append(u)
            if u["race"]:
                self.units_by_race[u["race"]].append(u)
            land = u["country"] or u["dragonflight"]
            if land:
                self.units_by_land[land].append(u)

        # Reverse indexes for cross-links -------------------------------------------------
        self.events_by_asset = defaultdict(list)     # granted asset id -> events
        self.events_by_country = defaultdict(list)   # alliance/requirement country -> events
        self.events_by_unit = defaultdict(list)      # resolved unit slug -> events
        self.artifacts_by_country = defaultdict(list)
        for eid, ev in self.events.items():
            for key, value in ev["effects"].items():
                if key == "grant_asset" and value in self.artifacts:
                    self.events_by_asset[value].append(eid)
                if key == "alliance" and value in self.countries:
                    self.events_by_country[value].append(eid)
                if key == "add_units":
                    for slug in self.resolve_add_units(value, ev["allegiance"]):
                        self.events_by_unit[slug].append(eid)
            for req in ev["requirements"]:
                if isinstance(req, dict) and req.get("type") == "country_active":
                    cid = req.get("id")
                    if cid in self.countries:
                        self.events_by_country[cid].append(eid)
        for aid, art in self.artifacts.items():
            for req in art["requirements"]:
                if not isinstance(req, dict):
                    continue
                if req.get("type") == "country":
                    value = req.get("value")
                    if value in self.countries:
                        self.artifacts_by_country[value].append(aid)
            diplomacy = art["bonus"].get("diplomacy") if isinstance(art["bonus"], dict) else None
            for cid in diplomacy or []:
                if cid in self.countries:
                    self.artifacts_by_country[cid].append(aid)

        # Bonus type index: bonus key -> artifact ids that grant it -----------------------
        self.bonuses_index = defaultdict(list)
        for aid, art in self.artifacts.items():
            bonus = art["bonus"] if isinstance(art["bonus"], dict) else {}
            keys = {k for k in bonus if k != "other"}
            if bonus.get("other"):
                keys.add(bonus["other"])
            for k in keys:
                self.bonuses_index[k].append(aid)
        self.bonus_ref = {k: (en, es, en_desc, es_desc)
                          for k, en, es, en_desc, es_desc in self.BONUS_REFERENCE}

    # --- localization helpers -----------------------------------------------------------
    def _name(self, kind, key, default=""):
        value = _get(self.en, kind, key, default=default)
        if isinstance(value, dict):
            value = value.get("name", default)
        return value

    def _name_es(self, kind, key, default=None):
        value = _get(self.es, kind, key, default=default)
        if isinstance(value, dict):
            value = value.get("name", default)
        return value

    def L(self, kind, key, default=""):
        en = self._name(kind, key, default)
        es = self._name_es(kind, key, default or en)
        return l10n_span(en, es, en_only=es is None)

    def lbl(self, en, es):
        return l10n_span(en, es)

    # --- links --------------------------------------------------------------------------
    def link_unit(self, u):
        slug = u["raw_id"] if u["named"] else u["slug"]
        return self._link("unit", slug, u["name_html"])

    def link(self, kind, target, label_html):
        return self._link(kind, target, label_html)

    def _link(self, kind, target, label_html):
        return f'<a class="l-x" data-goto="{kind}/{target}" href="#{kind}/{target}">{label_html}</a>'

    def land_link(self, u):
        if u["country"]:
            return self._link("country", u["country"], self.country_name(u["country"]))
        if u["dragonflight"]:
            return self._link("group", u["dragonflight"], self.country_name(u["dragonflight"]))
        return None

    def country_name(self, cid, default=None):
        return self.L("countries", cid, default or cid)

    def resolve_add_units(self, value, allegiance=None):
        if not value:
            return []
        if value in self.units_by_id:
            return [self.units_by_id[value]["slug"]]
        if value in self.ADD_UNITS_ALIASES:
            return list(self.ADD_UNITS_ALIASES[value])
        if allegiance:
            matches = lambda u: (u.get("allegiance") or "") == allegiance
        else:
            matches = lambda u: True
        if value in self.units_by_type:
            return [u["slug"] for u in self.units_by_type[value] if matches(u)]
        if value in self.units_by_race:
            return [u["slug"] for u in self.units_by_race[value] if matches(u)]
        return []

    # --- rendering ----------------------------------------------------------------------
    def render_unit_name(self, u):
        if u["named"]:
            en = self._name("unit_names", u["raw_id"], u["raw_id"].replace("_", " ").title())
            es = self._name_es("unit_names", u["raw_id"], en)
            return l10n_span(en, es, en_only=es is None)
        race_en = self._name("races", u["race"], u["race"] or "")
        race_es = self._name_es("races", u["race"], race_en)
        type_en = (self._name("unit_types", u["unit_type"], "") or u["unit_type"] or "").title()
        type_es = self._name_es("unit_types", u["unit_type"], type_en)
        return l10n_span(f"{race_en} {type_en}".strip(), f"{race_es} {type_es}".strip().title())

    def img(self, picture, fallback, xclass="card-img"):
        candidates = [picture] if picture else []
        if fallback not in candidates:
            candidates.append(fallback)
        for pic in candidates:
            if pic and os.path.exists(os.path.join(IMAGES_DIR, pic)):
                return f'<img class="{xclass}" src="../img/{_esc(pic)}" alt="" loading="lazy" onerror="this.style.display=&#39;none&#39;">'
        return ""

    def badge(self, text_html, kind="gray"):
        return f'<span class="badge badge-{kind}">{text_html}</span>'

    def allegiance_badge(self, alleg):
        if not alleg:
            return ""
        en, es = self.ALLEGIANCE_LABELS.get(alleg, (alleg.title(), alleg.title()))
        return self.badge(l10n_span(en, es), kind=alleg)

    def build(self, inline=False):
        self.inline = bool(inline)
        parts = []
        parts.append(self._head())
        parts.append(self._header())
        parts.append('<main>')
        parts.append(self._units_tab())
        parts.append(self._artifacts_tab())
        parts.append(self._events_tab())
        parts.append(self._countries_tab())
        parts.append(self._bonuses_tab())
        parts.append(self._rules_tab())
        parts.append('</main>')
        parts.append(self._footer())
        parts.append(self._scripts())
        return "\n".join(parts)

    # --- tabs ---------------------------------------------------------------------------
    def _section_open(self, tab_id, title_html, count):
        return (
            f'<section class="tab" id="{tab_id}">'
            f'<h2 class="sr-only">{title_html}</h2>'
            f'<div class="empty" hidden><span class="l10n" data-en="No matches">No matches</span></div>'
        )

    def _units_tab(self):
        cards = []
        for u in self.units:
            u["name_html"] = self.render_unit_name(u)
        # Group units by allegiance, then by land.
        grouped = defaultdict(lambda: defaultdict(list))
        for u in sorted(self.units, key=lambda x: x["raw_id"]):
            alleg = u["allegiance"] or "neutral"
            landed = u["country"] or u["dragonflight"] or None
            grouped[alleg][landed].append(u)

        allegiance_order = ["whitestone", "highlord", "neutral"]
        htmls = [self._section_open("tab-units", self.lbl("Units", "Unidades"), len(self.units))]
        for alleg in allegiance_order:
            if alleg not in grouped:
                continue
            section_title = self.allegiance_badge(alleg)
            htmls.append(f'<div class="alleg-sec"><h3 class="alleg-title">{section_title}</h3>')
            for land in sorted(grouped[alleg].keys(), key=lambda k: (k or "")):
                units_here = grouped[alleg][land]
                if land is None:
                    head = self.lbl("Independent", "Independientes")
                elif land in DRAGONFLIGHTS:
                    head = self.badge(self.country_name(land), "dragon")
                else:
                    head = self.link("country", land, self.country_name(land))
                htmls.append(f'<div class="group" id="group-{_esc(land or "independent")}">')
                htmls.append(f'<h4 class="group-title">{head} <span class="count">{sum(u["quantity"] for u in units_here)}</span></h4>')
                htmls.append('<div class="grid">')
                for u in sorted(units_here, key=lambda x: self._sort_unit(x)):
                    htmls.append(self._unit_card(u))
                htmls.append('</div></div>')
            htmls.append('</div>')
        htmls.append('</section>')
        return "\n".join(htmls)

    def _sort_unit(self, u):
        return (not u["named"], (self._name("unit_names", u["raw_id"]) if u["named"] else
                                 self._name("races", u["race"], u["race"] or "")).lower())

    def _unit_card(self, u):
        terms = [
            self._name("unit_names", u["raw_id"], "") if u["named"] else "",
            self._name("races", u["race"], "") if not u["named"] else "",
            self._name("unit_types", u["unit_type"], ""),
            u["country"] or u["dragonflight"] or "",
        ]
        terrain = u["terrain_affinity"] or ""
        meta = []
        land_link = self.land_link(u)
        if land_link:
            meta.append(land_link)
        if terrain:
            meta.append(self.badge(self.lbl("Terrain", "Terreno") + f' {_esc(terrain)}'))

        rating_bit = ""
        tactical = u["tactical_rating"]
        if tactical is not None and tactical != 0:
            rating_bit = f'<b>{self.lbl("Tactical", "Táctico")}</b> {tactical}'
        elif u["combat_rating"] is not None:
            rating_bit = f'<b>{self.lbl("Combat", "Combate")}</b> {u["combat_rating"]}'
        move_bit = f'<b>{self.lbl("Movement", "Movimiento")}</b> {u["movement"]}' if u["movement"] is not None else ""
        if rating_bit or move_bit:
            stats = (
                f'<ul class="stats">'
                f'<li class="stat-row"><span class="stat-val">{rating_bit}</span>'
                f'<span class="stat-move">{move_bit}</span></li>'
                f'</ul>'
            )
        else:
            stats = ""

        type_badge = self.badge(self.L("unit_types", u["unit_type"], (u["unit_type"] or "").title()))
        race_badge = ""
        if u["race"]:
            race_badge = self.badge(self.L("races", u["race"], (u["race"] or "").title()))
        qty = f'<span class="qty">×{u["quantity"]}</span>' if (not u["named"] and u["quantity"] > 1) else ""
        search = " ".join(x for x in terms if x) + " " + terrain
        return (
            f'<article class="card unit" id="unit-card-{_esc(u["slug"])}" data-search="{_esc(search.lower())}">'
            f'{self.img(u["picture"], "army.jpg")}'
            f'<div class="card-body">'
            f'<h4 class="card-title">{u["name_html"]} {qty}</h4>'
            f'<div class="badges">{self.allegiance_badge(u["allegiance"])}{type_badge}{race_badge}</div>'
            f'<p class="meta">{" · ".join(meta) if meta else ""}</p>'
            f'{stats}'
            f'</div></article>'
        )

    def _artifacts_tab(self):
        htmls = [self._section_open("tab-artifacts", self.lbl("Artifacts", "Artefactos"), len(self.artifacts))]
        htmls.append('<div class="grid">')
        for aid in sorted(self.artifacts.keys(), key=lambda a: self._name("assets", a, a).lower()):
            htmls.append(self._artifact_card(self.artifacts[aid]))
        htmls.append('</div></section>')
        return "\n".join(htmls)

    def _artifact_card(self, art):
        art_type = self.ARTICLE_TYPE_LABELS.get(art["type"], (art["type"], art["type"]))
        badges = [self.badge(l10n_span(*art_type))]
        if art["is_consumable"]:
            badges.append(self.badge(self.lbl("Consumable", "Consumible"), "hl"))

        terms = [self._name("assets", art["id"], art["id"]), art["id"], art["type"]]
        req_html = self._requirements_html(art["requirements"], intent="artifact")
        bonus_html = ""
        if art["bonus"]:
            bonus_html = self._bonus_html(art["bonus"])

        granted_by = self.events_by_asset.get(art["id"], [])
        granted_html = ""
        if granted_by:
            links = " · ".join(self.link("event", eid, self.L("events", eid, eid)) for eid in granted_by)
            granted_html = f'<p class="links"><b>{self.lbl("Granted by", "Obtenido mediante")}:</b> {links}</p>'

        effect_html = ""
        if art["effect"]:
            effect_html = f'<p class="desc effect"><b>{self.lbl("Effect", "Efecto")}:</b> {_esc(art["effect"])}</p>'

        return (
            f'<article class="card artifact" id="artifact-card-{_esc(art["id"])}" '
            f'data-search="{_esc(" ".join(terms).lower())}">'
            f'{self.img(art["picture"], "artifact.jpg", "card-img artifact-img")}'
            f'<div class="card-body">'
            f'<h4 class="card-title">{self.L("assets", art["id"], art["id"].replace("_", " ").title())}</h4>'
            f'<div class="badges">{"".join(badges)}{self.allegiance_badge(self._asset_allegiance(art))}</div>'
            f'<p class="desc">{_esc(art["description"])}</p>'
            f'{effect_html}'
            f'{bonus_html}'
            f'{req_html}'
            f'{granted_html}'
            f'</div></article>'
        )

    def _asset_allegiance(self, art):
        for req in art["requirements"]:
            if isinstance(req, dict) and req.get("type") == "allegiance":
                return req.get("value")
        return None

    def _bonus_html(self, bonus):
        if not isinstance(bonus, dict):
            return ""
        bits = []
        if bonus.get("tactical_rating"):
            bits.append(f'<li>{self.lbl("Tactical Rating", "Táctico")}: +{bonus["tactical_rating"]}</li>')
        if bonus.get("combat_rating"):
            bits.append(f'<li>{self.lbl("Combat Rating", "Combate")}: {bonus["combat_rating"]}</li>')
        diplomacy = bonus.get("diplomacy")
        if diplomacy:
            links = " · ".join(self.link("country", c, self.country_name(c)) for c in diplomacy)
            bits.append(f'<li>{self.lbl("Diplomacy bonus", "Bonificación diplomática")}: {links}</li>')
        others = {k: v for k, v in bonus.items() if k not in ("tactical_rating", "combat_rating", "diplomacy")}
        for k, v in others.items():
            if k == "other":
                ref = self.bonus_ref.get(v)
                if ref:
                    bits.append(f'<li>{self.link("bonus", v, l10n_span(ref[0], ref[1]))}</li>')
                    continue
            bits.append(f'<li>{_esc(k if isinstance(k, str) else str(k))}: {_esc(v)}</li>')
        if not bits:
            return ""
        return f'<p class="links"><b>{self.lbl("Bonus", "Bonificación")}:</b></p><ul class="kv">{ "".join(bits) }</ul>'

    def _events_tab(self):
        htmls = [self._section_open("tab-events", self.lbl("Events", "Eventos"), len(self.events))]
        ordered = sorted(self.events.values(), key=lambda e: (e["turn"] if e["turn"] is not None else 9999,
                                                             self._name("events", e["id"], e["id"]).lower()))
        for ev in ordered:
            htmls.append(self._event_card(ev))
        htmls.append('</section>')
        return "\n".join(htmls)

    def _event_card(self, ev):
        ev_type = self.EVENT_TYPE_LABELS.get(ev["type"], (ev["type"], ev["type"]))
        badges = [self.badge(l10n_span(*ev_type))]
        if ev["turn"] is not None:
            badges.append(self.badge(self.lbl("Turn", "Turno") + f' {ev["turn"]}'))
        badges.append(self.allegiance_badge(ev["allegiance"]))
        if ev["max_occurrences"]:
            badges.append(self.badge(self.lbl("×" + str(ev["max_occurrences"]), "×" + str(ev["max_occurrences"])), "gray"))

        effects_html = self._effects_html(ev["effects"], ev["allegiance"])
        req_html = self._requirements_html(ev["requirements"], intent="event")
        terms = [self._name("events", ev["id"], ev["id"]), ev["id"], ev["type"]]
        return (
            f'<article class="card event" id="event-card-{_esc(ev["id"])}" '
            f'data-search="{_esc(" ".join(terms).lower())}">'
            f'{self.img(ev["picture"], "event.jpg", "card-img event-img")}'
            f'<div class="card-body">'
            f'<h4 class="card-title">{self.L("events", ev["id"], ev["id"].replace("_", " ").title())}</h4>'
            f'<div class="badges">{"".join(badges)}</div>'
            f'<p class="desc">{_esc(ev["description"])}</p>'
            f'{req_html}'
            f'{effects_html}'
            f'</div></article>'
        )

    def _effects_html(self, effects, allegiance=None):
        if not effects:
            return ""
        bits = []
        labels = {
            "grant_asset": self.lbl("Grants", "Otorga"),
            "add_units": self.lbl("Adds", "Añade"),
            "alliance": self.lbl("Alliance with", "Alianza con"),
            "activation_bonus": self.lbl("Activation bonus", "Bonificación de activación"),
            "combat_bonus": self.lbl("Combat bonus", "Bonificación de combate"),
        }
        for key, value in effects.items():
            label = labels.get(key)
            if key == "grant_asset":
                if value in self.artifacts:
                    body = self.link("artifact", value, self.L("assets", value, value))
                else:
                    body = _esc(value)
                bits.append(f'<li>{label}: {body}</li>')
            elif key == "add_units":
                slugs = self.resolve_add_units(value, allegiance)
                if slugs:
                    links = " · ".join(
                        self.link("unit", s, self._unit_name_by_slug(s)) for s in slugs)
                    body = links if links else _esc(value)
                else:
                    body = _esc(value)
                bits.append(f'<li>{label}: {body}</li>')
            elif key == "alliance":
                if value in self.countries:
                    body = self.link("country", value, self.country_name(value))
                else:
                    body = _esc(value)
                bits.append(f'<li>{label}: {body}</li>')
            elif isinstance(value, (int, float)):
                plus = "+" if value > 0 else ""
                bits.append(f'<li>{label}: {plus}{value}</li>')
            else:
                bits.append(f'<li>{label if label else _esc(key)}: {_esc(value)}</li>')
        return f'<p class="links"><b>{self.lbl("Effects", "Efectos")}:</b></p><ul class="kv affect">{"".join(bits)}</ul>'

    def _unit_name_by_slug(self, slug):
        u = None
        for candidate in self.units:
            if (candidate["raw_id"] if candidate["named"] else candidate["slug"]) == slug:
                u = candidate
                break
        if not u:
            return slug
        return self.render_unit_name(u)

    def _requirements_html(self, requirements, intent):
        if not requirements:
            return ""
        bits = []
        for req in requirements:
            if not isinstance(req, dict):
                continue
            req_type = req.get("type")
            value = req.get("value") or req.get("id") or ""
            if req_type in ("country_active", "country"):
                if value in self.countries:
                    bits.append(f'<li>{self.link("country", value, self.country_name(value))}</li>')
                elif value in DRAGONFLIGHTS:
                    bits.append(f'<li>{self.link("group", value, self.country_name(value))}</li>')
                else:
                    bits.append(f'<li>{_esc(value)}</li>')
            elif req_type == "asset":
                if value in self.artifacts:
                    bits.append(f'<li>{self.link("artifact", value, self.L("assets", value, value))}</li>')
                else:
                    bits.append(f'<li>{_esc(value)}</li>')
            else:
                bits.append(f'<li>{_esc(req_type or "")}: {_esc(value)}</li>')
        return f'<p class="links"><b>{self.lbl("Requirements", "Requisitos")}:</b></p><ul class="kv">{ "".join(bits) }</ul>'

    def _countries_tab(self):
        htmls = [self._section_open("tab-countries", self.lbl("Countries", "Naciones"), len(self.countries))]
        htmls.append('<div class="grid">')
        for cid in sorted(self.countries.keys(), key=lambda c: self._name("countries", c, c).lower()):
            htmls.append(self._country_card(self.countries[cid]))
        htmls.append('</div></section>')
        return "\n".join(htmls)

    def _country_card(self, c):
        cid = c["id"]
        allegiance = self.allegiance_badge(c["allegiance"])
        tags = "".join(self.badge(_esc(t.replace("_", " "))) for t in c["tags"])

        loc_bits = []
        for lid, info in c["locations"].items():
            ltype = info.get("loc_type", "city")
            lt = self.LOCATION_TYPES.get(ltype, (ltype, ltype))
            coords = info.get("coords", [0, 0])
            loc_bits.append(
                f'<li>{_esc(self._name("locations", lid, lid))} '
                f'<span class="dim">({l10n_span(*lt)}) [{coords[0]},{coords[1]}]</span></li>'
            )

        cap_bits = []
        if c["capital_id"]:
            cap_bits.append(f'<li><b>{self.lbl("Capital", "Capital")}</b> {_esc(self._name("locations", c["capital_id"], c["capital_id"]))}</li>')
        if c["strength"]:
            cap_bits.append(f'<li><b>{self.lbl("Strength", "Poder Militar")}</b> {c["strength"]}</li>')
        if c["alignment"] and any(c["alignment"]):
            cap_bits.append(f'<li><b>{self.lbl("Alignment WS/HL", "Alineación PB/SD")}</b> {c["alignment"][0]:+d} / {c["alignment"][1]:+d}</li>')
        if c["territories"]:
            cap_bits.append(f'<li><b>{self.lbl("Territories", "Territorios")}</b> {len(c["territories"])}</li>')

        units_here = self.units_by_land.get(cid, [])
        unit_items = "".join(
            f'<li>{self.link_unit(u)} <span class="qty">x{u["quantity"]}</span></li>'
            for u in units_here
        )
        units_html = f'<p class="links"><b>{self.lbl("Units", "Unidades")} ({sum(u["quantity"] for u in units_here)}):</b></p>' \
                     f'<ul class="kv">{unit_items}</ul>' if unit_items else ""

        event_links = " · ".join(self.link("event", eid, self.L("events", eid, eid)) for eid in sorted(set(self.events_by_country.get(cid, []))))
        events_html = f'<p class="links"><b>{self.lbl("Related events", "Eventos relacionados")}:</b></p>' \
                      f'<ul class="kv">{ "".join(f"<li>{u}</li>" for u in self._chunk_links(event_links)) }</ul>' if event_links else ""

        artifact_links = " · ".join(self.link("artifact", aid, self.L("assets", aid, aid)) for aid in sorted(set(self.artifacts_by_country.get(cid, []))))
        artifacts_html = f'<p class="links"><b>{self.lbl("Related artifacts", "Artefactos relacionados")}:</b></p>' \
                         f'<ul class="kv">{ "".join(f"<li>{u}</li>" for u in self._chunk_links(artifact_links)) }</ul>' if artifact_links else ""

        swatch = f'<span class="swatch" style="background:{_esc(c["color"]) or "#888"}" title="{_esc(c["color"] or "")}"></span>'
        search = " ".join([self._name("countries", cid, cid), cid, c["allegiance"]]) + " " + \
                 " ".join(self._name("locations", lid, lid) for lid in c["locations"])
        return (
            f'<article class="card country" id="country-card-{_esc(cid)}" '
            f'data-search="{_esc(search.lower())}">'
            f'<div class="card-body">'
            f'<h4 class="card-title">{self.country_name(cid)} {swatch}</h4>'
            f'<div class="badges">{allegiance}{tags}</div>'
            f'<ul class="kv">{"".join(cap_bits)}{"".join(loc_bits)}</ul>'
            f'{units_html}{events_html}{artifacts_html}'
            f'</div></article>'
        )

    def _chunk_links(self, joined):
        return [it for it in joined.split(" · ") if it] if joined else []

    def _bonuses_tab(self):
        keys = [k for k, *_ in self.BONUS_REFERENCE if k in self.bonuses_index]
        htmls = [self._section_open("tab-bonuses", self.lbl("Bonuses", "Bonus"), len(keys))]
        htmls.append('<div class="grid">')
        for key, en_name, es_name, en_desc, es_desc in self.BONUS_REFERENCE:
            if key in self.bonuses_index:
                htmls.append(self._bonus_card(key, en_name, es_name, en_desc, es_desc))
        htmls.append('</div></section>')
        return "\n".join(htmls)

    def _bonus_card(self, key, en_name, es_name, en_desc, es_desc):
        if key not in self.bonus_ref:
            en_desc, es_desc = self.GENERIC_BONUS
        ids = sorted(set(self.bonuses_index.get(key, [])),
                     key=lambda a: self._name("assets", a, a).lower())
        links = " · ".join(self.link("artifact", aid, self.L("assets", aid, aid)) for aid in ids)
        artifacts_html = ""
        if links:
            artifacts_html = (
                f'<p class="links"><b>{self.lbl("Artifacts", "Artefactos")}:</b></p>'
                f'<ul class="kv">{"".join(f"<li>{u}</li>" for u in self._chunk_links(links))}</ul>'
            )
        search = f'{key} {en_name} {es_name}'
        return (
            f'<article class="card bonus" id="bonus-card-{_esc(key)}" '
            f'data-search="{_esc(search.lower())}">'
            f'<div class="card-body">'
            f'<h4 class="card-title">{l10n_span(en_name, es_name)}</h4>'
            f'<p class="desc">{l10n_span(en_desc, es_desc)}</p>'
            f'{artifacts_html}'
            f'</div></article>'
        )

    # --- rules manual --------------------------------------------------------------------
    def _manual_locale(self, *path):
        """Fetch a (en, es) value pair from the 'manual' locale namespace."""
        return (_get(self.en, "manual", *path, default=None),
                _get(self.es, "manual", *path, default=None))

    def _manual_title(self, sec_id, sub_id=None):
        path = (sec_id,) if sub_id is None else (sec_id, sub_id)
        en, es = self._manual_locale(*path, "title")
        if not en and not es:
            print(f"WARNING: missing manual title for manual.{'.'.join(path)}", file=sys.stderr)
            return f"<code>{sec_id if sub_id is None else sub_id}</code>"
        return l10n_span(en, es)

    def _manual_link(self, kind, tid):
        if kind in ("country", "group"):
            label = self.L("countries", tid, tid)
        elif kind == "artifact":
            label = self.L("assets", tid, tid)
        elif kind == "event":
            label = self.L("events", tid, tid)
        elif kind == "unit":
            label = self.L("unit_names", tid, tid)
        else:
            label = self.lbl(tid, tid)
        return (f'<a class="l-x" data-goto="{_esc(kind)}/{_esc(tid)}" '
                f'href="#{_esc(kind)}/{_esc(tid)}">{label}</a>')

    def _manual_rich(self, en, es):
        """Render a bilingual string, honouring [[kind:id]] markers."""
        ep = _MANUAL_LINK_RE.split(en or "")
        sp = _MANUAL_LINK_RE.split(es or "")
        out = []
        i = 0
        while i < len(ep):
            te = ep[i]
            ts = sp[i] if i < len(sp) else ep[i]
            if te or ts:
                out.append(l10n_span(te, ts))
            i += 1
            if i >= len(ep):
                break
            kind, tid = ep[i], ep[i + 1]
            out.append(self._manual_link(kind, tid))
            i += 2
        return "".join(out)

    def _manual_crt(self):
        """Render the Combat Results Table grid straight from data/crt.csv."""
        try:
            with open(CRT_DATA, encoding="utf-8") as f:
                rows = [[c.strip() for c in rec] for rec in csv.reader(f, delimiter=";")]
        except OSError as e:
            print(f"WARNING: could not read CRT data: {e}", file=sys.stderr)
            return ""
        if not rows:
            print("WARNING: CRT data file is empty", file=sys.stderr)
            return ""
        thead = []
        for idx, c in enumerate(rows[0]):
            thead.append(f"<th>{l10n_span('Roll', 'Tirada') if idx == 0 else _esc(c)}</th>")
        body = []
        for rec in rows[1:]:
            body.append("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in rec) + "</tr>")
        return ('<div class="tblwrap"><table class="mtable crt"><thead><tr>'
                + "".join(thead) + "</tr></thead><tbody>" + "".join(body)
                + "</tbody></table></div>")

    def _manual_calendar(self):
        """Render the campaign calendar straight from data/calendar.csv."""
        try:
            with open(CALENDAR_DATA, encoding="utf-8") as f:
                rows = [[c.strip() for c in rec] for rec in csv.reader(f, delimiter=";")]
        except OSError as e:
            print(f"WARNING: could not read calendar data: {e}", file=sys.stderr)
            return ""
        if not rows:
            print("WARNING: calendar data file is empty", file=sys.stderr)
            return ""
        headers = (l10n_span("Turn", "Turno"), l10n_span("Period", "Periodo"),
                   l10n_span("Year", "Año"))
        thead = "".join(f"<th>{h}</th>" for h in headers)
        body = []
        for rec in rows[1:]:
            if len(rec) < 3:
                continue
            winter = rec[1].lower() == "winter"
            cls = ' class="winter"' if winter else ""
            body.append(f"<tr{cls}>" + "".join(f"<td>{_esc(c)}</td>" for c in rec[:3]) + "</tr>")
        return ('<div class="tblwrap"><table class="mtable cal"><thead><tr>'
                + thead + "</tr></thead><tbody>" + "".join(body)
                + "</tbody></table></div>")

    def _manual_alignment(self):
        """Render the country alignment table from data/countries.yaml."""
        items = []
        for cid in sorted(self.countries.keys(),
                          key=lambda c: self._name("countries", c, c).lower()):
            c = self.countries[cid]
            name = self._manual_link("country", cid)
            strength = c["strength"] or "—"
            ws, hl = c["alignment"][:2] if len(c["alignment"]) >= 2 else (0, 0)
            items.append(
                f'<tr><td>{name}</td><td>{strength}</td>'
                f'<td>{ws:+d}</td><td>{hl:+d}</td></tr>'
            )
        thead = "".join(
            f"<th>{h}</th>" for h in (l10n_span("Country", "Nación"),
                                      l10n_span("Strength", "Poder Militar"),
                                      l10n_span("WS", "PB"), l10n_span("HL", "SD"))
        )
        return ('<div class="tblwrap"><table class="mtable align"><thead><tr>'
                + thead + "</tr></thead><tbody>" + "".join(items)
                + "</tbody></table></div>")

    def _manual_terrain(self):
        """Ground movement cost per terrain (standard/winter) with terrain images."""
        thead = "".join(
            f"<th>{h}</th>" for h in (l10n_span("Hex", "Hexágono"),
                                      l10n_span("Terrain", "Terreno"),
                                      l10n_span("Cost", "Coste"),
                                      l10n_span("Cost in winter", "Coste en invierno"))
        )
        body = []
        for key, std, win in TERRAIN_ROWS:
            name = self.L("terrain", key, key.title())
            if std == "—" and win == "—":
                cls = ' class="impassable"'
            else:
                cls = ""
            body.append(
                f'<tr{cls}><td><img class="hex" src="../img/{key}.png" '
                f'alt="{_esc(key.title())}" loading="lazy"></td><td>{name}</td>'
                f"<td>{_esc(std)}</td><td>{_esc(win)}</td></tr>"
            )
        return ('<div class="tblwrap"><table class="mtable terr"><thead><tr>'
                + thead + "</tr></thead><tbody>" + "".join(body)
                + "</tbody></table></div>")

    def _manual_block(self, sec_id, sub_id, b):
        t = b.get("t", "p")
        if t == "crt":
            return self._manual_crt()
        if t == "calendar":
            return self._manual_calendar()
        if t == "align":
            return self._manual_alignment()
        if t == "terrain":
            return self._manual_terrain()
        key = b.get("key", "")
        en, es = self._manual_locale(sec_id, sub_id, key)
        if en is None and es is None:
            print(f"WARNING: missing manual locale key manual.{sec_id}.{sub_id}.{key}", file=sys.stderr)
            return ""
        t = b.get("t", "p")
        if t == "p":
            return f'<p class="mp">{self._manual_rich(en, es)}</p>'
        if t in ("ul", "ol"):
            en_items = en if isinstance(en, list) else []
            es_items = es if isinstance(es, list) else []
            tag = "ul" if t == "ul" else "ol"
            items = []
            for idx, item_en in enumerate(en_items):
                item_es = es_items[idx] if idx < len(es_items) else item_en
                items.append(f"<li>{self._manual_rich(item_en, item_es)}</li>")
            return f'<{tag} class="ml">{"".join(items)}</{tag}>'
        if t == "warn":
            en_d = en if isinstance(en, dict) else {}
            es_d = es if isinstance(es, dict) else {}
            head = ""
            et = en_d.get("title") or ""
            st = es_d.get("title") or et
            if et:
                head = f'<div class="m-warn-title">{l10n_span(et, st)}</div>'
            return f'<div class="m-warn">{head}{self._manual_rich(en_d.get("text", ""), es_d.get("text", ""))}</div>'
        if t == "tbl":
            en_d = en if isinstance(en, dict) else {}
            es_d = es if isinstance(es, dict) else {}
            hed = []
            en_h = en_d.get("headers") or []
            es_h = es_d.get("headers") or []
            for idx, hen in enumerate(en_h):
                hes = es_h[idx] if idx < len(es_h) else hen
                hed.append(f"<th>{l10n_span(hen, hes)}</th>")
            rows_html = []
            en_rows = en_d.get("rows") or []
            es_rows = es_d.get("rows") or []
            for ridx, erow in enumerate(en_rows):
                es_row = es_rows[ridx] if ridx < len(es_rows) else erow
                cells = []
                for cidx, cen in enumerate(erow):
                    ces = es_row[cidx] if isinstance(es_row, list) and cidx < len(es_row) else cen
                    cells.append(f"<td>{self._manual_rich(cen, ces)}</td>")
                rows_html.append("<tr>" + "".join(cells) + "</tr>")
            body = "".join(rows_html)
            return (f'<div class="tblwrap"><table class="mtable"><thead><tr>{"".join(hed)}</tr></thead>'
                    f'<tbody>{body}</tbody></table></div>')
        return ""

    def _manual_pager(self, sec_id):
        idx = next(i for i, s in enumerate(MANUAL_SECTIONS) if s["id"] == sec_id)
        prev_sec = MANUAL_SECTIONS[idx - 1] if idx > 0 else None
        next_sec = MANUAL_SECTIONS[idx + 1] if idx < len(MANUAL_SECTIONS) - 1 else None
        nav = ['<div class="m-pager">']
        if prev_sec:
            nav.append(f'<a class="m-page" href="#m-{prev_sec["id"]}" rel="prev">&larr; '
                       f'{self._manual_title(prev_sec["id"])}</a>')
        else:
            nav.append('<span></span>')
        if next_sec:
            nav.append(f'<a class="m-page" href="#m-{next_sec["id"]}" rel="next">'
                       f'{self._manual_title(next_sec["id"])} &rarr;</a>')
        elif prev_sec:
            nav.append('<span></span>')
        nav.append("</div>")
        return "\n".join(nav)

    def _manual_toc(self):
        h = ['<nav class="m-toc" aria-label="Manual sections">']
        for sec in MANUAL_SECTIONS:
            sec_id = f'm-{sec["id"]}'
            h.append(f'<a class="m-toc-link" href="#{sec_id}" data-sec="{sec_id}">'
                     f'{self._manual_title(sec["id"])}</a>')
        h.append("</nav>")
        return "\n".join(h)

    def _manual_body(self):
        h = []
        for sec in MANUAL_SECTIONS:
            sec_id = sec["id"]
            h.append(f'<section class="m-sec" id="m-{sec_id}">')
            h.append(f'<h4 class="m-title">{self._manual_title(sec_id)}</h4>')
            for sub_id, blocks in sec["subsections"].items():
                h.append(f'<article class="m-sub" id="ms-{sub_id}">')
                h.append(f'<h5 class="m-subtitle">{self._manual_title(sec_id, sub_id)}</h5>')
                for blk in blocks:
                    h.append(self._manual_block(sec_id, sub_id, blk))
                h.append("</article>")
            h.append(self._manual_pager(sec_id))
            h.append("</section>")
        return "\n".join(h)

    def _rules_tab(self):
        h = []
        h.append(self._section_open("tab-rules", self.lbl("Rules", "Reglas"), 0))
        h.append('<div class="rules-panel">')
        h.append(f'<h3>{self.lbl("Game Rules", "Reglas del juego")}</h3>')
        intro_en, intro_es = self._manual_locale("intro")
        if intro_en or intro_es:
            h.append(f'<p class="desc">{l10n_span(intro_en, intro_es)}</p>')
        h.append('<div class="manual">')
        h.append('<aside class="manual-toc">')
        h.append(f'<div class="m-toc-title">{self.lbl("Table of Contents", "Índice")}</div>')
        h.append(self._manual_toc())
        h.append('</aside>')
        h.append('<div class="manual-body">')
        h.append(self._manual_body())
        h.append('</div>')
        h.append('</div>')
        h.append('<div class="manual-appendix">')
        h.append(f'<h4>{self.lbl("Official Rulebooks", "Manuales oficiales")}</h4>')
        pdfs = [
            ("manual.pdf", self.lbl("Manual", "Manual"),
             self.lbl("The complete game manual.", "El manual completo del juego.")),
            ("advanced_rules.pdf", self.lbl("Advanced Rules", "Reglas avanzadas"),
             self.lbl("Advanced and optional rules.", "Reglas avanzadas y opcionales.")),
            ("house_rules.pdf", self.lbl("House Rules", "Reglas de la casa"),
             self.lbl("Community house rules (Brian Bradford).", "Reglas de la casa de la comunidad (Brian Bradford).")),
        ]
        for fname, title, blurb in pdfs:
            href = f"../doc/{fname}"
            h.append(
                f'<div class="card rules-card">'
                f'<div class="card-body">'
                f'<h4 class="card-title"><a class="pdf-link" href="{href}" target="_blank">{title} '
                f'<span class="dim">PDF</span></a></h4>'
                f'<p class="desc">{blurb}</p>'
                f'</div></div>'
            )
        note_en = ("This wiki is generated from the game data (units.csv, artifacts.yaml, events.yaml, "
                   "countries.yaml) by scripts/build_wiki.py. Lore text is authored in English; "
                   "names and labels are shown in English or Spanish with the EN/ES toggle.")
        note_es = ("Esta wiki se genera a partir de los datos del juego (units.csv, artifacts.yaml, "
                   "events.yaml, countries.yaml) mediante scripts/build_wiki.py. El texto de ambientación "
                   "está escrito en inglés; los nombres y etiquetas se muestran en inglés o español con el "
                   "conmutador EN/ES.")
        h.append(f'<p class="note desc">{l10n_span(note_en, note_es)}</p>')
        h.append('</div>')
        h.append('</div>')
        h.append('</section>')
        return "\n".join(h)

    # --- chrome -------------------------------------------------------------------------
    def _head(self):
        return (
            '<!DOCTYPE html>\n'
            '<html lang="en">\n'
            '<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>Dragons of Glory — Wiki</title>\n'
            + self._css() +
            '</head>\n'
        )

    def _header(self):
        tab_count = {
            "units": len(self.units),
            "artifacts": len(self.artifacts),
            "events": len(self.events),
            "countries": len(self.countries),
            "bonuses": len(self.bonuses_index),
        }
        tabs = []
        for key in ("rules", "units", "artifacts", "events", "countries", "bonuses"):
            en, es = self.SECTION_LABELS[key]
            n = tab_count.get(key)
            label = l10n_span(f"{en} ({n})" if n else en, f"{es} ({n})" if n else es)
            tabs.append(f'<button class="tab-btn" data-tab="tab-{key}" role="tab" aria-selected="false">{label}</button>')
        return (
            '<header class="topbar">\n'
            '<div class="topbar-row">\n'
            f'<h1 class="l10n" data-en="Dragons of Glory — Game Wiki" data-es="Dragons of Glory — Wiki del juego">Dragons of Glory — Game Wiki</h1>\n'
            '<div class="topbar-tools">\n'
            '<span id="search-count" class="dim"></span>\n'
            '<input id="wiki-search" type="search" role="searchbox" '
            'placeholder="Search name, type, country, race..." aria-label="Search">\n'
            '<button id="lang-btn" class="chip" type="button" title="Toggle language">ES</button>\n'
            '</div>\n'
            '</div>\n'
            '<nav class="tabs" role="tablist">\n' + "\n".join(tabs) + '</nav>\n'
            '</header>\n'
        )

    def _footer(self):
        return (
            '<footer class="footer">\n'
            '<p class="dim"><span class="l10n" data-en="Generated by scripts/build_wiki.py from the game data files." '
            'data-es="Generado por scripts/build_wiki.py a partir de los archivos de datos del juego.">'
            'Generated by scripts/build_wiki.py from the game data files.</span></p>\n'
            '</footer>\n'
        )

    def _css(self):
        if self.inline:
            return "<style>\n" + _read_text(WIKI_CSS) + "\n</style>\n"
        return f'<link rel="stylesheet" href="{_esc(os.path.basename(WIKI_CSS))}">\n'

    def _scripts(self):
        if self.inline:
            return "<script>\n" + _read_text(WIKI_JS) + "\n</script>\n</body>\n</html>\n"
        return f'<script src="{_esc(os.path.basename(WIKI_JS))}"></script>\n</body>\n</html>\n'


def l10n_span(en, es=None, en_only=False):
    """Build a language-aware span. Falls back to English when Spanish is missing."""
    ents = _esc(en)
    part = f'data-en="{ents}"'
    if not en_only and es is not None and es != en:
        part += f' data-es="{_esc(es)}"'
    return f'<span class="l10n" {part}>{ents}</span>'


def build_wiki_html(inline=False) -> str:
    return WikiGen().build(inline=inline)


def main():
    inline = "--inline" in sys.argv[1:]
    out_dir = os.path.dirname(WIKI_HTML)
    os.makedirs(out_dir, exist_ok=True)
    with open(WIKI_HTML, "w", encoding="utf-8") as fh:
        fh.write(build_wiki_html(inline=inline))
    suffix = " (self-contained)" if inline else " (external wiki.css/wiki.js)"
    print(f"Wiki written to {WIKI_HTML}{suffix}")


if __name__ == "__main__":
    sys.exit(main())