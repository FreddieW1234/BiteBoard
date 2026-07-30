"""Allergen / dietary sentence mapping and Shopify tab body_html builder."""

from __future__ import annotations

# Suitable-for metafields: tick/cross (✔️ / ❌) stored as-is.
SUITABLE_FOR_KEYS = ("vegan", "vegetarian", "halal", "coeliac", "kosher")

# Allergen metafields: store full sentence, not dropdown label.
ALLERGEN_KEYS = (
    "celery",
    "cereals",
    "crustaceans",
    "egg",
    "fish",
    "lupin",
    "milk",
    "molluscs",
    "mustard",
    "nuts",
    "peanuts",
    "sesame",
    "soya",
    "sulphurdioxide",
)

# Legacy key merged into ``nuts`` when reading.
LEGACY_ALLERGEN_KEY_ALIASES = {"tree_nuts": "nuts"}

ALLERGEN_SENTENCES = {
    "celery": {
        "contains": "Celery present as an ingredient.",
        "may_contain": "Possible cross-contact with celery.",
        "free_from": "No celery intentionally used and no credible cross-contact risk.",
    },
    "cereals": {
        "contains": "Gluten-containing cereal present as an ingredient.",
        "may_contain": "Possible cross-contact with gluten-containing cereals.",
        "free_from": "No gluten-containing cereals intentionally used and controlled to avoid cross-contact.",
    },
    "crustaceans": {
        "contains": "Crustaceans present as an ingredient.",
        "may_contain": "Possible cross-contact with crustaceans.",
        "free_from": "No crustaceans intentionally used and controlled to avoid cross-contact.",
    },
    "egg": {
        "contains": "Eggs present as an ingredient.",
        "may_contain": "Possible cross-contact with eggs.",
        "free_from": "No eggs intentionally used and controlled to avoid cross-contact.",
    },
    "fish": {
        "contains": "Fish present as an ingredient.",
        "may_contain": "Possible cross-contact with fish.",
        "free_from": "No fish intentionally used and controlled to avoid cross-contact.",
    },
    "lupin": {
        "contains": "Lupin present as an ingredient.",
        "may_contain": "Possible cross-contact with lupin.",
        "free_from": "No lupin intentionally used and controlled to avoid cross-contact.",
    },
    "milk": {
        "contains": "Milk present as an ingredient.",
        "may_contain": "Possible cross-contact with milk.",
        "free_from": "No milk intentionally used and controlled to avoid cross-contact.",
    },
    "molluscs": {
        "contains": "Molluscs present as an ingredient.",
        "may_contain": "Possible cross-contact with molluscs.",
        "free_from": "No molluscs intentionally used and controlled to avoid cross-contact.",
    },
    "mustard": {
        "contains": "Mustard present as an ingredient.",
        "may_contain": "Possible cross-contact with mustard.",
        "free_from": "No mustard intentionally used and controlled to avoid cross-contact.",
    },
    "nuts": {
        "contains": "Nuts present as an ingredient.",
        "may_contain": "Possible cross-contact with nuts.",
        "free_from": "No nuts intentionally used and controlled to avoid cross-contact.",
    },
    "peanuts": {
        "contains": "Peanuts present as an ingredient.",
        "may_contain": "Possible cross-contact with peanuts.",
        "free_from": "No peanuts intentionally used and controlled to avoid cross-contact.",
    },
    "sesame": {
        "contains": "Sesame seeds present as an ingredient.",
        "may_contain": "Possible cross-contact with sesame.",
        "free_from": "No sesame intentionally used and controlled to avoid cross-contact.",
    },
    "soya": {
        "contains": "Soya present as an ingredient.",
        "may_contain": "Possible cross-contact with soya.",
        "free_from": "No soya intentionally used and controlled to avoid cross-contact.",
    },
    "sulphurdioxide": {
        "contains": "Sulphites present above the threshold.",
        "may_contain": "Possible cross-contact or trace presence.",
        "free_from": "No sulphites above the threshold and controlled to avoid contamination.",
    },
}

BODY_SUITABLE_LABELS = {
    "vegan": "Suitable for Vegans",
    "vegetarian": "Suitable for Vegetarians",
    "halal": "Halal (Not certified)",
    "coeliac": "Suitable for Coeliac",
    "kosher": "Suitable for Kosher",
}

BODY_ALLERGEN_LABELS = {
    "celery": "Celery",
    "cereals": "Cereals containing gluten",
    "crustaceans": "Crustaceans",
    "egg": "Egg",
    "fish": "Fish",
    "lupin": "Lupin",
    "milk": "Milk",
    "molluscs": "Molluscs",
    "mustard": "Mustard",
    "nuts": "Nuts",
    "peanuts": "Peanuts",
    "sesame": "Sesame Seeds",
    "soya": "Soya",
    "sulphurdioxide": "Sulphur Dioxide",
}

DIETARY_SECTION_HEADING = "Dietary/Allergens"

# Shopify native description (body_html) — Product Info section only (not custom.description SEO field).
PRODUCT_INFO_METAFIELD_KEY = "productinfo"


def allergen_sentence(key: str, level: str) -> str:
    k = (key or "").strip().lower()
    lvl = (level or "").strip().lower().replace(" ", "_")
    if lvl == "may contain":
        lvl = "may_contain"
    if lvl == "free from":
        lvl = "free_from"
    mapping = ALLERGEN_SENTENCES.get(k) or {}
    return mapping.get(lvl) or ""


def infer_allergen_level(key: str, stored_value: str) -> str:
    """Return ``contains`` | ``may_contain`` | ``free_from`` | ``''`` from stored metafield text."""
    val = (stored_value or "").strip()
    if not val:
        return ""
    if val in ("✔️", "✅"):
        return "contains"
    if val in ("❌",):
        return "free_from"
    k = (key or "").strip().lower()
    mapping = ALLERGEN_SENTENCES.get(k) or {}
    for level, sentence in mapping.items():
        if val == sentence:
            return level
    val_lower = val.lower()
    for level, sentence in mapping.items():
        if sentence.lower() == val_lower:
            return level
    return ""


def _normalize_mf_map(mf_map: dict) -> dict:
    out = dict(mf_map or {})
    if not (out.get("nuts") or "").strip() and (out.get("tree_nuts") or "").strip():
        out["nuts"] = out["tree_nuts"]
    return out


def build_dietary_allergens_section_lines(mf_map: dict) -> list[str]:
    mf = _normalize_mf_map(mf_map)
    lines = []
    for key in SUITABLE_FOR_KEYS:
        val = (mf.get(key) or "").strip()
        if val:
            label = BODY_SUITABLE_LABELS.get(key, key)
            lines.append(f"{label} {val}")
    for key in ALLERGEN_KEYS:
        val = (mf.get(key) or "").strip()
        if val:
            label = BODY_ALLERGEN_LABELS.get(key, key)
            lines.append(f"{label} {val}")
    return lines


def plain_text_to_shopify_h3_html(text: str) -> str:
    if not text or not str(text).strip():
        return ""
    parts = []
    for line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        escaped = (
            line.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        parts.append(f"<h3><span>{escaped}</span><span></span></h3>")
    return "\n".join(parts)


# Shopify native description (body_html) — tab headings only; tab content comes from metafields on the theme.
SHOPIFY_NATIVE_DESCRIPTION_HTML = (
    "<h3><span>Product Info</span><span></span></h3>\n"
    "<h3><span>Ingredients</span><span></span></h3>\n"
    "<h3><span>Dietary/Allergens</span><span></span><span></span></h3>"
)


def shopify_native_description_html() -> str:
    return SHOPIFY_NATIVE_DESCRIPTION_HTML


def build_shopify_body_html_from_metafield_map(_mf_map=None) -> str:
    """Native product description is fixed tab headings only (not metafield content)."""
    return shopify_native_description_html()


def metafields_list_to_map(metafields) -> dict:
    out = {}
    for mf in metafields or []:
        ns = (mf.get("namespace") or "").strip().lower()
        if ns != "custom":
            continue
        key = (mf.get("key") or "").strip()
        if key:
            out[key] = mf.get("value")
    return _normalize_mf_map(out)
