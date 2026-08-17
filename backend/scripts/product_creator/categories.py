"""
Category and Subcategory definitions for product metafields

This file contains the preset choices for the custom metafields:
- custom.custom_category
- custom.subcategory
- custom.parent_child / custom.parent_child2 - Parent/Child options are read live from
  Shopify metafield definition choice lists (PARENT_CHILD_CHOICES below is fallback only)
- custom.parent_child2 (overflow when parent_child hits Shopify's choice-list limit)

Category/subcategory/filter lists below are still maintained in this file.
"""

import json
import os
import time

import requests

# Fallback Parent/Child choices if Shopify metafield definitions cannot be read.
# Live source of truth: Shopify Admin -> metafield definitions for
# custom.parent_child and custom.parent_child2 (choices validation).
PARENT_CHILD_CHOICES = [
    "Parent - Chocolate Bar Mini",
    "Child - Chocolate Bar Mini",
    "Parent - Chocolate Bar Midi",
    "Child - Chocolate Bar Midi",
    "Parent - Chocolate Bar Maxi",
    "Child - Chocolate Bar Maxi",
    "Parent - Neo",
    "Child - Neo",
    "Parent - Chunky Milk Chocolate Bar Wrap",
    "Child - Chunky Milk Chocolate Bar Wrap",
    "Parent - Organza Bag - Mini Chocolate Hearts",
    "Child - Organza Bag - Mini Chocolate Hearts",
    "Parent - Assorted Flat Lollipops - Envelope",
    "Child - Assorted Flat Lollipops - Envelope",
    "Parent - Assorted Flat Lollipops",
    "Child - Assorted Flat Lollipops",
    "Parent - Chocolate Coin Net",
    "Child - Chocolate Coin Net",
    "Parent - Choc Chip Cookie Bag",
    "Child - Choc Chip Cookie Bag",
    "Parent - Assorted Biscuits Maxi Quad Box",
    "Child - Assorted Biscuits Maxi Quad Box",
    "Parent - Jelly Beans - Mini A Box",
    "Child - Jelly Beans - Mini A Box",
    "Parent - Pick n Mix Jellies Mini A Box",
    "Child - Pick n Mix Jellies Mini A Box",
    "Parent - Mini A Box Hearts",
    "Child - Mini A Box Hearts",
    "Parent - Skittles Bag",
    "Child - Skittles Bag",
    "Parent - Skittles Postal Pack",
    "Child - Skittles Postal Pack",
    "Parent - Jelly Beans Postal Pack",
    "Child - Jelly Beans Postal Pack",
    "Parent - Jelly Bears Postal Pack",
    "Child - Jelly Bears Postal Pack",
    "Parent - Strawberry Millions Postal Pack",
    "Child - Strawberry Millions Postal Pack",
    "Parent - Strawberry Millions Mini A Box",
    "Child - Strawberry Millions Mini A Box",
    "Parent - Chocolate M&M's",
    "Child - Chocolate M&M's",
    "Parent - Crispy M&M's",
    "Child - Crispy M&M's",
    "Parent - Mini Cuboid - Two Roses",
    "Child - Mini Cuboid - Two Roses",
    "Parent - Mini Cuboid - Two Heroes",
    "Child - Mini Cuboid - Two Heroes",
    "Parent - Mini Cuboid - Two Celebrations",
    "Child - Mini Cuboid - Two Celebrations",
    "Parent - Mini Cuboid - Two Quality Street",
    "Child - Mini Cuboid - Two Quality Street",
    "Parent - Mini Cuboid - Chocolate Hearts",
    "Child - Mini Cuboid - Chocolate Hearts",
    "Parent - Mini Cube - Chocolate Hearts",
    "Child - Mini Cube - Chocolate Hearts",
    "Parent - Roses Midi Quad",
    "Child - Roses Midi Quad",
    "Parent - Heroes Midi Quad",
    "Child - Heroes Midi Quad",
    "Parent - Celebrations Midi Quad",
    "Child - Celebrations Midi Quad",
    "Parent - Shortbread Fingers Midi Quad",
    "Child - Shortbread Fingers Midi Quad",
    "Parent - Dates Midi Quad",
    "Child - Dates Midi Quad",
    "Parent - Midi Quad - Quality Street",
    "Child - Midi Quad - Quality Street",
    "Parent - Organza Bag - Celebrations",
    "Child - Organza Bag - Celebrations",
    "Parent - Organza Bag - Quality Street",
    "Child - Organza Bag - Quality Street",
    "Parent - Organza Bag - Roses",
    "Child - Organza Bag - Roses",
    "Parent - Organza Bag - Heroes",
    "Child - Organza Bag - Heroes",
    "Parent - Organza Bag - Stars",
    "Child - Organza Bag - Stars",
    "Parent - Organza Bag - Coins",
    "Child - Organza Bag - Coins",
    "Parent - Organza Bag - Retro Sweets",
    "Child - Organza Bag - Retro Sweets",
    "Parent - Organza Bag - Lindt Truffle",
    "Child - Organza Bag - Lindt Truffle",
    "Parent - Creme Egg Organza Bag",
    "Child - Creme Egg Organza Bag",
    "Parent - Lindt Lindor Egg Organza Bag",
    "Child - Lindt Lindor Egg Organza Bag",
    "Parent - Caramel Egg Organza Bag",
    "Child - Caramel Egg Organza Bag",
    "Parent - McVitie's Mini Gingerbread Men Bag",
    "Child - McVitie's Mini Gingerbread Men Bag",
    "Parent - Fox's Mini Party Rings Bag",
    "Child - Fox's Mini Party Rings Bag",
    "Parent - Tetley Black Tea Envelope",
    "Child - Tetley Black Tea Envelope",
    "Parent - Pringles Original Mini Tub",
    "Child - Pringles Original Mini Tub",
    "Parent - Sweet Microwave Popcorn",
    "Child - Sweet Microwave Popcorn",
    "Parent - Toffee Popcorn Bag",
    "Child - Toffee Popcorn Bag",
    "Parent - Shirt Box Chocolate",
    "Child - Shirt Box Chocolate",
    "Parent - Haribo Tangfastics Header bag",
    "Child - Haribo Tangfastics Header bag",
    "Parent - Haribo Starmix Header bag",
    "Child - Haribo Starmix Header bag",
    "Parent - Jelly Beans Header Bag",
    "Child - Jelly Beans Header Bag",
    "Parent - Jelly Bears Header Bag",
    "Child - Jelly Bears Header Bag",
    "Parent - Jelly Beans Organza Bag",
    "Child - Jelly Beans Organza Bag",
    "Parent - Love Hearts Organza Bag",
    "Child - Love Hearts Organza Bag",
    "Parent - Popcorn Bag",
    "Child - Popcorn Bag",
    "Parent - Jammie Dodger Bag",
    "Child - Jammie Dodger Bag",
    "Parent - Strawberry Millions Bag",
    "Child - Strawberry Millions Bag",
    "Parent - Jelly Bears Mini A Box",
    "Child - Jelly Bears Mini A Box",
    "Parent - 12 Day Advent Calendar",
    "Child - 12 Day Advent Calendar",
]

# Overflow boundary: parent_child2 contains this item and everything after it in PARENT_CHILD_CHOICES.
# Shopify limits choice lists to 128 options (~64 families); parent_child2 continues the same list.
PARENT_CHILD2_FIRST_ITEM = "Parent - Jelly Bears Mini A Box"

# Legacy optional ID map for resolving a Parent type -> product ID when the live
# store scan cannot find one. Parent/Child dropdown options and Create-from-Parent
# lists now come from Shopify metafield definition choices + live product scan.
PARENT_PRODUCTS = [
    {"title": "Chocolate Bar Mini", "parent_child_value": "Parent - Chocolate Bar Mini", "id": None},
    {"title": "Chocolate Bar Midi", "parent_child_value": "Parent - Chocolate Bar Midi", "id": None},
    {"title": "Chocolate Bar Maxi", "parent_child_value": "Parent - Chocolate Bar Maxi", "id": None},
    {"title": "Neo", "parent_child_value": "Parent - Neo", "id": None},
    {"title": "Chunky Milk Chocolate Bar Wrap", "parent_child_value": "Parent - Chunky Milk Chocolate Bar Wrap", "id": None},
    {"title": "Organza Bag - Mini Chocolate Hearts", "parent_child_value": "Parent - Organza Bag - Mini Chocolate Hearts", "id": None},
    {"title": "Assorted Flat Lollipops - Envelope", "parent_child_value": "Parent - Assorted Flat Lollipops - Envelope", "id": None},
    {"title": "Assorted Flat Lollipops", "parent_child_value": "Parent - Assorted Flat Lollipops", "id": None},
    {"title": "Chocolate Coin Net", "parent_child_value": "Parent - Chocolate Coin Net", "id": None},
    {"title": "Choc Chip Cookie Bag", "parent_child_value": "Parent - Choc Chip Cookie Bag", "id": None},
    {"title": "Assorted Biscuits Maxi Quad Box", "parent_child_value": "Parent - Assorted Biscuits Maxi Quad Box", "id": None},
    {"title": "Jelly Beans - Mini A Box", "parent_child_value": "Parent - Jelly Beans - Mini A Box", "id": None},
    {"title": "Pick n Mix Jellies Mini A Box", "parent_child_value": "Parent - Pick n Mix Jellies Mini A Box", "id": None},
    {"title": "Mini A Box Hearts", "parent_child_value": "Parent - Mini A Box Hearts", "id": None},
    {"title": "Skittles Bag", "parent_child_value": "Parent - Skittles Bag", "id": None},
    {"title": "Skittles Postal Pack", "parent_child_value": "Parent - Skittles Postal Pack", "id": None},
    {"title": "Jelly Beans Postal Pack", "parent_child_value": "Parent - Jelly Beans Postal Pack", "id": None},
    {"title": "Jelly Bears Postal Pack", "parent_child_value": "Parent - Jelly Bears Postal Pack", "id": None},
    {"title": "Strawberry Millions Postal Pack", "parent_child_value": "Parent - Strawberry Millions Postal Pack", "id": None},
    {"title": "Strawberry Millions Mini A Box", "parent_child_value": "Parent - Strawberry Millions Mini A Box", "id": None},
    {"title": "Chocolate M&M's", "parent_child_value": "Parent - Chocolate M&M's", "id": None},
    {"title": "Crispy M&M's", "parent_child_value": "Parent - Crispy M&M's", "id": None},
    {"title": "Mini Cuboid - Two Roses", "parent_child_value": "Parent - Mini Cuboid - Two Roses", "id": None},
    {"title": "Mini Cuboid - Two Heroes", "parent_child_value": "Parent - Mini Cuboid - Two Heroes", "id": None},
    {"title": "Mini Cuboid - Two Celebrations", "parent_child_value": "Parent - Mini Cuboid - Two Celebrations", "id": None},
    {"title": "Mini Cuboid - Two Quality Street", "parent_child_value": "Parent - Mini Cuboid - Two Quality Street", "id": None},
    {"title": "Mini Cuboid - Chocolate Hearts", "parent_child_value": "Parent - Mini Cuboid - Chocolate Hearts", "id": None},
    {"title": "Mini Cube - Chocolate Hearts", "parent_child_value": "Parent - Mini Cube - Chocolate Hearts", "id": None},
    {"title": "Roses Midi Quad", "parent_child_value": "Parent - Roses Midi Quad", "id": None},
    {"title": "Heroes Midi Quad", "parent_child_value": "Parent - Heroes Midi Quad", "id": None},
    {"title": "Celebrations Midi Quad", "parent_child_value": "Parent - Celebrations Midi Quad", "id": None},
    {"title": "Shortbread Fingers Midi Quad", "parent_child_value": "Parent - Shortbread Fingers Midi Quad", "id": None},
    {"title": "Dates Midi Quad", "parent_child_value": "Parent - Dates Midi Quad", "id": None},
    {"title": "Midi Quad - Quality Street", "parent_child_value": "Parent - Midi Quad - Quality Street", "id": None},
    {"title": "Organza Bag - Celebrations", "parent_child_value": "Parent - Organza Bag - Celebrations", "id": None},
    {"title": "Organza Bag - Quality Street", "parent_child_value": "Parent - Organza Bag - Quality Street", "id": None},
    {"title": "Organza Bag - Roses", "parent_child_value": "Parent - Organza Bag - Roses", "id": None},
    {"title": "Organza Bag - Heroes", "parent_child_value": "Parent - Organza Bag - Heroes", "id": None},
    {"title": "Organza Bag - Stars", "parent_child_value": "Parent - Organza Bag - Stars", "id": None},
    {"title": "Organza Bag - Coins", "parent_child_value": "Parent - Organza Bag - Coins", "id": None},
    {"title": "Organza Bag - Retro Sweets", "parent_child_value": "Parent - Organza Bag - Retro Sweets", "id": None},
    {"title": "Organza Bag - Lindt Truffle", "parent_child_value": "Parent - Organza Bag - Lindt Truffle", "id": None},
    {"title": "Creme Egg Organza Bag", "parent_child_value": "Parent - Creme Egg Organza Bag", "id": None},
    {"title": "Lindt Lindor Egg Organza Bag", "parent_child_value": "Parent - Lindt Lindor Egg Organza Bag", "id": None},
    {"title": "Caramel Egg Organza Bag", "parent_child_value": "Parent - Caramel Egg Organza Bag", "id": None},
    {"title": "McVitie's Mini Gingerbread Men Bag", "parent_child_value": "Parent - McVitie's Mini Gingerbread Men Bag", "id": None},
    {"title": "Fox's Mini Party Rings Bag", "parent_child_value": "Parent - Fox's Mini Party Rings Bag", "id": None},
    {"title": "Tetley Black Tea Envelope", "parent_child_value": "Parent - Tetley Black Tea Envelope", "id": None},
    {"title": "Pringles Original Mini Tub", "parent_child_value": "Parent - Pringles Original Mini Tub", "id": None},
    {"title": "Sweet Microwave Popcorn", "parent_child_value": "Parent - Sweet Microwave Popcorn", "id": None},
    {"title": "Toffee Popcorn Bag", "parent_child_value": "Parent - Toffee Popcorn Bag", "id": None},
    {"title": "Shirt Box Chocolate", "parent_child_value": "Parent - Shirt Box Chocolate", "id": None},
    {"title": "Haribo Tangfastics Header bag", "parent_child_value": "Parent - Haribo Tangfastics Header bag", "id": None},
    {"title": "Haribo Starmix Header bag", "parent_child_value": "Parent - Haribo Starmix Header bag", "id": None},
    {"title": "Jelly Beans Header Bag", "parent_child_value": "Parent - Jelly Beans Header Bag", "id": None},
    {"title": "Jelly Bears Header Bag", "parent_child_value": "Parent - Jelly Bears Header Bag", "id": None},
    {"title": "Jelly Beans Organza Bag", "parent_child_value": "Parent - Jelly Beans Organza Bag", "id": None},
    {"title": "Love Hearts Organza Bag", "parent_child_value": "Parent - Love Hearts Organza Bag", "id": None},
    {"title": "Popcorn Bag", "parent_child_value": "Parent - Popcorn Bag", "id": None},
    {"title": "Jammie Dodger Bag", "parent_child_value": "Parent - Jammie Dodger Bag", "id": None},
    {"title": "Strawberry Millions Bag", "parent_child_value": "Parent - Strawberry Millions Bag", "id": None},
    {"title": "Jelly Bears Mini A Box", "parent_child_value": "Parent - Jelly Bears Mini A Box", "id": None},
    {"title": "12 Day Advent Calendar", "parent_child_value": "Parent - 12 Day Advent Calendar", "id": None},
]

# Filter groups: each is a SEPARATE Shopify metafield (List / choice list, single line text)
# but they are all shown together in ONE dropdown in Product Manager, grouped under bold
# (non-selectable) headings.
#
# IMPORTANT: the "namespace"/"key" and every option below must match the Shopify metafield
# definitions EXACTLY, or saving/loading will fail. To create these in Shopify, add one
# "List > Choice list (single line text)" metafield per group using the namespace.key shown.
FILTER_GROUPS = [
    {
        "heading": "Packaging",
        "namespace": "custom",
        "key": "packaging",
        "options": ["Bag", "Box", "Tin", "Envelope", "Gift Pack", "Individually Wrapped", "Bulk"],
    },
    {
        "heading": "Size",
        "namespace": "custom",
        "key": "size",
        "options": ["Mini", "Midi", "Maxi"],
    },
    {
        "heading": "Brand",
        "namespace": "custom",
        "key": "brand",
        "options": ["Haribo", "Lindt", "Swizzles"],
    },
    {
        "heading": "Eco",
        "namespace": "custom",
        "key": "eco",
        "options": ["Eco-Friendly Packaging", "Plastic Free Packaging"],
    },
]

# Set of filter metafield keys (used by the UI to know which metafields feed the combined dropdown)
FILTER_GROUP_KEYS = [g["key"] for g in FILTER_GROUPS]

# Category choices for custom.custom_category metafield
CATEGORIES = [
    "Chocolate",
    "Sweets",
    "Dietary",
    "Biscuits & Cakes",
    "Snacks",
    "Drinks",
    "Seasonal",
    "Industries",
    "Events",
    "Food & Pantry",
    "Branded Merchandise & Packaging",
]

# Subcategory choices for custom.subcategory metafield
# This list is the flat (de-duplicated) set of all subcategories, organized by category
# (order matches CATEGORY_MAPPING). "Lollipops" is shared by Chocolate and Sweets, so it
# appears once here but is mapped to both categories in CATEGORY_MAPPING.
SUBCATEGORIES = [
    # Chocolate
    "Favourites",
    "Bars",
    "Assorted",
    "Shapes & Novelties",
    "Lollipops",
    "Advent Calendars",
    # Sweets
    "Gums & Jellies",
    "Toffees & Chews",
    "Boiled & Hard",
    "Mints",
    "Fudge, Nougat & Coconut Ice",
    "Sherbet & Fizzy",
    "Retro & Novelty",
    # Dietary
    "Vegan",
    "Vegetarian",
    "Gluten Free",
    "Dairy Free",
    # Biscuits & Cakes
    "Biscuits & Cookies",
    "Cake Bars, Slices & Flapjacks",
    "Mini Cakes & Cupcakes",
    "Cakes & Traybakes",
    # Snacks
    "Crisps & Chips",
    "Popcorn",
    "Pretzels",
    "Nuts, Dried Fruit & Savoury Mixes",
    "Rice Cakes & Corn Cakes",
    "Crackers & Savoury Biscuits",
    "Protein, Cereal & Energy Bars",
    "Snack Pots & Dippers",
    # Drinks
    "Tea",
    "Coffee",
    "Hot Chocolate & Malt Drinks",
    "Soft Drinks",
    "Juices",
    "Water & Flavoured Water",
    "Energy & Sports Drinks",
    # Seasonal
    "Valentine's Day",
    "Chinese New Year",
    "Easter",
    "Mother's Day",
    "Father's Day",
    "Summer",
    "Ramadan & Eid",
    "Diwali",
    "Halloween",
    "Hanukkah",
    "Christmas",
    "New Year",
    # Industries
    "Retail",
    "Hospitality",
    "Offices & Services",
    "Education",
    "Health & Care",
    "Travel & Leisure",
    "Media & Creative",
    "Trade & Construction",
    # Events
    "Appreciation & Workplace Events",
    "Fun & Feel Good Days",
    "Community Charities & Causes",
    "Wellbeing & Inclusion Events",
    "Sports Events",
    # Food & Pantry
    "Cereal & Porridge",
    "Soup",
    "Pasta & Noodles",
    "Rice & Grains",
    "Desserts",
    "Baking Kits",
    "Spreads, Jams & Condiments",
    "Herbs, Spices & Seasonings",
    "Ice & Freeze Pops",
    # Branded Merchandise & Packaging
    "Packaging",
    "Merchandise",
    "Fulfillment Service",
]

# Overflow boundary: subcategory_2 contains this item and everything after it in SUBCATEGORIES.
# All current subcategories fit within Shopify's 128-choice limit, so they all live in the
# single "subcategory" metafield and subcategory_2 stays empty (set to None).
SUBCATEGORY_2_FIRST_ITEM = None

# Shopify requires at least one choice to create a list definition. subcategory_2 was
# seeded with this placeholder; it is replaced on first real overflow append and must
# never appear in Product Creator / category UIs.
SUBCATEGORY_2_PLACEHOLDER = "BLANK"


def is_subcategory_overflow_placeholder(value) -> bool:
    return str(value or "").strip().upper() == SUBCATEGORY_2_PLACEHOLDER


def filter_subcategory_placeholders(choices):
    """Drop BLANK (and case variants) from choice lists used in the product UI."""
    return [c for c in (choices or []) if not is_subcategory_overflow_placeholder(c)]

# Category to subcategory mapping
# This dictionary stores which subcategories belong to which categories
# Format: {"Category Name": ["Subcategory1", "Subcategory2", ...]}
CATEGORY_MAPPING = {
    "Chocolate": [
        "Favourites",
        "Bars",
        "Assorted",
        "Shapes & Novelties",
        "Lollipops",
        "Advent Calendars",
    ],
    "Sweets": [
        "Gums & Jellies",
        "Toffees & Chews",
        "Boiled & Hard",
        "Mints",
        "Fudge, Nougat & Coconut Ice",
        "Sherbet & Fizzy",
        "Lollipops",
        "Retro & Novelty",
    ],
    "Dietary": [
        "Vegan",
        "Vegetarian",
        "Gluten Free",
        "Dairy Free",
    ],
    "Biscuits & Cakes": [
        "Biscuits & Cookies",
        "Cake Bars, Slices & Flapjacks",
        "Mini Cakes & Cupcakes",
        "Cakes & Traybakes",
    ],
    "Snacks": [
        "Crisps & Chips",
        "Popcorn",
        "Pretzels",
        "Nuts, Dried Fruit & Savoury Mixes",
        "Rice Cakes & Corn Cakes",
        "Crackers & Savoury Biscuits",
        "Protein, Cereal & Energy Bars",
        "Snack Pots & Dippers",
    ],
    "Drinks": [
        "Tea",
        "Coffee",
        "Hot Chocolate & Malt Drinks",
        "Soft Drinks",
        "Juices",
        "Water & Flavoured Water",
        "Energy & Sports Drinks",
    ],
    "Seasonal": [
        "Valentine's Day",
        "Chinese New Year",
        "Easter",
        "Mother's Day",
        "Father's Day",
        "Summer",
        "Ramadan & Eid",
        "Diwali",
        "Halloween",
        "Hanukkah",
        "Christmas",
        "New Year",
    ],
    "Industries": [
        "Retail",
        "Hospitality",
        "Offices & Services",
        "Education",
        "Health & Care",
        "Travel & Leisure",
        "Media & Creative",
        "Trade & Construction",
    ],
    "Events": [
        "Appreciation & Workplace Events",
        "Fun & Feel Good Days",
        "Community Charities & Causes",
        "Wellbeing & Inclusion Events",
        "Sports Events",
    ],
    "Food & Pantry": [
        "Cereal & Porridge",
        "Soup",
        "Pasta & Noodles",
        "Rice & Grains",
        "Desserts",
        "Baking Kits",
        "Spreads, Jams & Condiments",
        "Herbs, Spices & Seasonings",
        "Ice & Freeze Pops",
    ],
    "Branded Merchandise & Packaging": [
        "Packaging",
        "Merchandise",
        "Fulfillment Service",
    ],
}

_CATEGORY_CHOICE_CACHE = {
    "at": 0.0,
    "categories": None,
    "subcategories": None,
    "subcategory": None,
    "subcategory_2": None,
    "source": None,  # "live" | "cached" | "fallback"
    "fetched_at": None,
}
_CATEGORY_CHOICE_TTL_SEC = 300
_CHOICE_LKG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "category-choices-lkg.json",
)


def _read_choice_lkg():
    try:
        if not os.path.isfile(_CHOICE_LKG_PATH):
            return None
        with open(_CHOICE_LKG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if not data.get("categories") and not data.get("subcategories"):
            return None
        return data
    except Exception as exc:
        print(f"[error] choice LKG read failed: {exc}", flush=True)
        return None


def _write_choice_lkg(cats, sub, sub2, merged):
    if not cats and not merged:
        print("[error] choice LKG poison guard: refusing empty write", flush=True)
        return
    existing = _read_choice_lkg()
    if existing:
        old_n = len(existing.get("subcategories") or [])
        new_n = len(merged or [])
        if old_n > 0 and new_n < old_n * 0.5:
            print(
                f"[error] choice LKG poison guard: refusing shrink {old_n} -> {new_n}",
                flush=True,
            )
            return
    try:
        os.makedirs(os.path.dirname(_CHOICE_LKG_PATH), exist_ok=True)
        payload = {
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "categories": list(cats),
            "subcategory": list(sub),
            "subcategory_2": list(sub2),
            "subcategories": list(merged),
            "note": "Ephemeral on Render - same container only.",
        }
        with open(_CHOICE_LKG_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception as exc:
        print(f"[error] choice LKG write failed: {exc}", flush=True)


def _load_category_choice_cache(force=False):
    """Load custom_category + subcategory(+_2): live -> LKG -> hardcoded ERROR."""
    now = time.time()
    cached = _CATEGORY_CHOICE_CACHE
    if (
        not force
        and cached.get("categories") is not None
        and (now - float(cached.get("at") or 0)) < _CATEGORY_CHOICE_TTL_SEC
    ):
        return cached

    cats = fetch_shopify_metafield_definition_choices("custom", "custom_category")
    sub = fetch_shopify_metafield_definition_choices("custom", "subcategory")
    sub2 = fetch_shopify_metafield_definition_choices("custom", "subcategory_2")
    source = "live"
    if cats or sub:
        sub_seen = {c.lower() for c in sub}
        sub2 = filter_subcategory_placeholders(
            [c for c in sub2 if c.lower() not in sub_seen]
        )
        merged_subs = list(sub) + list(sub2)
        _write_choice_lkg(cats, sub, sub2, merged_subs)
    else:
        lkg = _read_choice_lkg()
        if lkg:
            cats = list(lkg.get("categories") or [])
            sub = list(lkg.get("subcategory") or [])
            sub2 = filter_subcategory_placeholders(lkg.get("subcategory_2") or [])
            merged_subs = filter_subcategory_placeholders(
                lkg.get("subcategories") or (sub + sub2)
            )
            source = "cached"
            print(
                "[warn] category choices serving LKG (Shopify empty/unavailable)",
                flush=True,
            )
        else:
            cats = list(CATEGORIES)
            sub = list(SUBCATEGORIES)
            sub2 = []
            merged_subs = list(sub)
            source = "fallback"
            print(
                "[error] category choices FALLBACK to hardcoded lists - "
                "Shopify unavailable and no LKG. Do not edit taxonomy.",
                flush=True,
            )

    cached["at"] = now
    cached["categories"] = list(cats)
    cached["subcategory"] = list(sub)
    cached["subcategory_2"] = list(sub2)
    cached["subcategories"] = list(merged_subs)
    cached["source"] = source
    cached["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(
        f"[ok] Category/subcategory choices loaded from {source}: "
        f"categories={len(cats)}, subcategory={len(sub)}, "
        f"subcategory_2={len(sub2)}, merged_subs={len(merged_subs)}",
        flush=True,
    )
    return cached


def refresh_category_choice_cache():
    """Force-refresh Shopify-backed category/subcategory choice cache."""
    return _load_category_choice_cache(force=True)


def get_category_choices():
    """Live custom.custom_category choices from Shopify; fallback to CATEGORIES."""
    cache = _load_category_choice_cache()
    return list(cache.get("categories") or CATEGORIES)


def get_subcategory_choices():
    """Live subcategory + subcategory_2 choices from Shopify; fallback to SUBCATEGORIES.

    subcategory_2 placeholder BLANK is never returned.
    """
    cache = _load_category_choice_cache()
    return filter_subcategory_placeholders(
        cache.get("subcategories") or SUBCATEGORIES
    )


def get_category_subcategory_groups():
    """
    Categories with subcategories (and optional children) for the combined
    Category & Subcategory dropdown.

    Prefers shop.custom.taxonomy; falls back to CATEGORY_MAPPING when unset.
    Each subcategory is {label, children: [labels...]} for L3 nesting.
    """
    try:
        from shopify_client import taxonomy as taxmod

        tax = taxmod.load_taxonomy(require=False)
        if tax:
            groups = []
            for c in tax:
                cat_name = c.get("category")
                if not cat_name:
                    continue
                subs_out = []
                for s in c.get("subcategories") or []:
                    label = s.get("label")
                    if not label:
                        continue
                    children = [
                        ch.get("label")
                        for ch in (s.get("children") or [])
                        if ch.get("label")
                    ]
                    subs_out.append({"label": label, "children": children})
                groups.append({"category": cat_name, "subcategories": subs_out})
            return groups
    except Exception as exc:
        print(f"[error] taxonomy groups unavailable, using CATEGORY_MAPPING: {exc}", flush=True)

    return [
        {
            "category": cat,
            "subcategories": [{"label": s, "children": []} for s in (subs or [])],
        }
        for cat, subs in CATEGORY_MAPPING.items()
    ]

def get_filter_groups():
    """
    Get the filter groups for the combined Filters dropdown.

    Each group maps to a separate Shopify metafield but is shown under one bold,
    non-selectable heading in the UI.

    Returns:
        list: List of {heading, namespace, key, options} dicts
    """
    return [
        {
            "heading": g["heading"],
            "namespace": g.get("namespace", "custom"),
            "key": g["key"],
            "options": list(g["options"]),
        }
        for g in FILTER_GROUPS
    ]

_PARENT_CHILD_SHOPIFY_CACHE = {
    "at": 0.0,
    "parent_child": None,
    "parent_child2": None,
    "merged": None,
    "source": None,  # "shopify" | "fallback"
}
_PARENT_CHILD_SHOPIFY_TTL_SEC = 300


def _shopify_admin_creds():
    """Return (domain, token, api_version) or (None, None, None)."""
    try:
        from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION  # type: ignore
        return STORE_DOMAIN, ACCESS_TOKEN, API_VERSION
    except Exception:
        try:
            import os
            import sys
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if backend_dir not in sys.path:
                sys.path.append(backend_dir)
            from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION  # type: ignore
            return STORE_DOMAIN, ACCESS_TOKEN, API_VERSION
        except Exception:
            return None, None, None


def fetch_shopify_metafield_definition_choices(namespace, key):
    """
    Read the predefined choice list from a Shopify product metafield definition.
    Returns a list of strings, or [] if missing / unavailable.
    """
    domain, token, api_version = _shopify_admin_creds()
    if not domain or not token:
        return []
    domain = str(domain).replace("https://", "").replace("http://", "").rstrip("/").strip()
    url = f"https://{domain}/admin/api/{api_version or '2024-10'}/graphql.json"
    query = """
    query getMetafieldDefinitionChoices($namespace: String!, $key: String!, $ownerType: MetafieldOwnerType!) {
      metafieldDefinitions(first: 1, namespace: $namespace, key: $key, ownerType: $ownerType) {
        edges {
          node {
            key
            validations {
              name
              value
            }
          }
        }
      }
    }
    """
    try:
        resp = requests.post(
            url,
            headers={
                "X-Shopify-Access-Token": token,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "variables": {
                    "namespace": namespace,
                    "key": key,
                    "ownerType": "PRODUCT",
                },
            },
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"[warn] Shopify metafield choices HTTP {resp.status_code} for {namespace}.{key}", flush=True)
            return []
        payload = resp.json() or {}
        if payload.get("errors"):
            print(f"[warn] Shopify metafield choices GraphQL errors for {namespace}.{key}: {payload.get('errors')}", flush=True)
            return []
        edges = (
            ((payload.get("data") or {}).get("metafieldDefinitions") or {}).get("edges")
            or []
        )
        if not edges:
            return []
        validations = (edges[0].get("node") or {}).get("validations") or []
        for validation in validations:
            if (validation.get("name") or "").strip().lower() != "choices":
                continue
            raw = validation.get("value")
            if raw is None:
                return []
            if isinstance(raw, list):
                return [str(x).strip() for x in raw if str(x).strip()]
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                return []
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
            return []
        return []
    except Exception as exc:
        print(f"[warn] Failed reading Shopify choices for {namespace}.{key}: {exc}", flush=True)
        return []


def _fallback_parent_child_chunks():
    """Hardcoded split used only when Shopify definitions are unavailable."""
    if not PARENT_CHILD2_FIRST_ITEM:
        return list(PARENT_CHILD_CHOICES), []
    try:
        boundary = PARENT_CHILD_CHOICES.index(PARENT_CHILD2_FIRST_ITEM)
    except ValueError:
        return list(PARENT_CHILD_CHOICES), []
    return list(PARENT_CHILD_CHOICES[:boundary]), list(PARENT_CHILD_CHOICES[boundary:])


def _load_parent_child_choice_cache(force=False):
    """Load/cached parent_child + parent_child2 choice lists from Shopify (or fallback)."""
    now = time.time()
    cached = _PARENT_CHILD_SHOPIFY_CACHE
    if (
        not force
        and cached.get("merged") is not None
        and (now - float(cached.get("at") or 0)) < _PARENT_CHILD_SHOPIFY_TTL_SEC
    ):
        return cached

    pc = fetch_shopify_metafield_definition_choices("custom", "parent_child")
    pc2 = fetch_shopify_metafield_definition_choices("custom", "parent_child2")
    source = "shopify"
    if not pc and not pc2:
        pc, pc2 = _fallback_parent_child_chunks()
        source = "fallback"
        print("[warn] Using hardcoded PARENT_CHILD_CHOICES fallback (Shopify definition choices empty)", flush=True)
    else:
        # Keep definition order; append overflow without duplicating.
        pc_set = {c.lower() for c in pc}
        pc2 = [c for c in pc2 if c.lower() not in pc_set]

    merged = list(pc) + list(pc2)
    cached["at"] = now
    cached["parent_child"] = list(pc)
    cached["parent_child2"] = list(pc2)
    cached["merged"] = merged
    cached["source"] = source
    print(
        f"[ok] Parent/Child choices loaded from {source}: "
        f"parent_child={len(pc)}, parent_child2={len(pc2)}, merged={len(merged)}",
        flush=True,
    )
    return cached


def refresh_parent_child_choices_cache():
    """Force-refresh the Shopify-backed Parent/Child choice cache."""
    return _load_parent_child_choice_cache(force=True)


def get_parent_child_choices(force_refresh=False):
    """Full merged Parent/Child choice list (parent_child + parent_child2) from Shopify."""
    cache = _load_parent_child_choice_cache(force=force_refresh)
    return list(cache.get("merged") or [])


def get_parent_child_metafield_key(parent_child_value):
    """
    Route a Parent/Child value to parent_child or parent_child2 (overflow metafield).
    Uses membership in each Shopify definition's choice list (trim-insensitive).
    """
    val = str(parent_child_value or "").strip()
    if not val:
        return "parent_child"
    cache = _load_parent_child_choice_cache()
    pc = cache.get("parent_child") or []
    pc2 = cache.get("parent_child2") or []

    def _index_in(choices):
        try:
            return choices.index(val)
        except ValueError:
            val_lower = val.lower()
            for i, choice in enumerate(choices):
                if str(choice).strip().lower() == val_lower:
                    return i
            return None

    if _index_in(pc) is not None:
        return "parent_child"
    if _index_in(pc2) is not None:
        return "parent_child2"
    # Unknown value: prefer overflow if the primary list looks full.
    if pc2 or len(pc) >= 120:
        return "parent_child2"
    return "parent_child"


def resolve_parent_child_choice_value(parent_child_value):
    """
    Map a Parent/Child value to the exact string in Shopify's choice list.

    Choice definitions sometimes include trailing spaces; Shopify requires an
    exact match. Prefer the definition's string when trim/case matches.
    Falls back to a trimmed value when the choice is not yet in either list.
    """
    val = str(parent_child_value or "").strip()
    if not val:
        return ""
    cache = _load_parent_child_choice_cache()
    val_lower = val.lower()
    for key in ("parent_child", "parent_child2"):
        for choice in (cache.get(key) or []):
            c = str(choice)
            if c == val:
                return c
            stripped = c.strip()
            if stripped == val or stripped.lower() == val_lower:
                return c
    return val


def _subcategory_2_start_index():
    """Index in SUBCATEGORIES where subcategory_2 starts. When SUBCATEGORY_2_FIRST_ITEM
    is None or not present, there is no overflow and everything stays in subcategory."""
    if not SUBCATEGORY_2_FIRST_ITEM:
        return len(SUBCATEGORIES)
    try:
        return SUBCATEGORIES.index(SUBCATEGORY_2_FIRST_ITEM)
    except ValueError:
        return len(SUBCATEGORIES)  # no overflow if sentinel missing


def get_metafield_choices(metafield_key):
    """
    Get choices for a specific metafield
    
    Args:
        metafield_key (str): The metafield key (e.g., "custom_category", "subcategory", "subcategory_2", etc.)
    
    Returns:
        list: List of choices for the specified metafield
    """
    if metafield_key == "custom_category":
        return get_category_choices()
    elif metafield_key == "subcategory":
        cache = _load_category_choice_cache()
        chunk = cache.get("subcategory")
        if chunk is not None and cache.get("source") in ("live", "cached", "shopify"):
            return list(chunk)
        idx = _subcategory_2_start_index()
        return list(SUBCATEGORIES[:idx])
    elif metafield_key == "subcategory_2":
        cache = _load_category_choice_cache()
        chunk = cache.get("subcategory_2")
        if chunk is not None and cache.get("source") in ("live", "cached", "shopify"):
            return filter_subcategory_placeholders(chunk)
        idx = _subcategory_2_start_index()
        return filter_subcategory_placeholders(SUBCATEGORIES[idx:])
    elif metafield_key.startswith("subcategory_"):
        # subcategory_3, etc. - not used currently; keep slice by 128 for future
        try:
            chunk_index = int(metafield_key.split("_")[-1]) - 1
            start_idx = chunk_index * 128
            end_idx = start_idx + 128
            return get_subcategory_choices()[start_idx:end_idx]
        except (ValueError, IndexError):
            return []
    elif metafield_key == "parent_child":
        cache = _load_parent_child_choice_cache()
        return list(cache.get("parent_child") or [])
    elif metafield_key == "parent_child2":
        cache = _load_parent_child_choice_cache()
        return list(cache.get("parent_child2") or [])
    else:
        # Filter group metafields (custom.packaging, custom.size, custom.brand, custom.eco)
        for group in FILTER_GROUPS:
            if group["key"] == metafield_key:
                return list(group["options"])
        return []

def get_subcategory_metafield_key(subcategory):
    """
    Route a subcategory value to custom.subcategory or custom.subcategory_2.
    Prefers live Shopify choice membership; falls back to SUBCATEGORIES index.
    """
    s = str(subcategory).strip()
    if not s:
        return "subcategory"

    cache = _load_category_choice_cache()
    if cache.get("source") in ("live", "cached", "shopify"):
        pc = cache.get("subcategory") or []
        pc2 = cache.get("subcategory_2") or []
        s_lower = s.lower()

        def _in(choices):
            for choice in choices:
                c = str(choice)
                if c == s or c.strip() == s or c.strip().lower() == s_lower:
                    return True
            return False

        if _in(pc):
            return "subcategory"
        if _in(pc2):
            return "subcategory_2"
        # Unknown: prefer overflow when primary looks full
        if pc2 or len(pc) >= 120:
            return "subcategory_2"
        return "subcategory"

    s_norm = " ".join(s.replace("\u00a0", " ").split())

    if s in SUBCATEGORIES:
        index = SUBCATEGORIES.index(s)
    elif s_norm in SUBCATEGORIES:
        index = SUBCATEGORIES.index(s_norm)
    else:
        s_lower = s_norm.lower()
        found = None
        for i, choice in enumerate(SUBCATEGORIES):
            c_norm = " ".join(str(choice).replace("\u00a0", " ").split())
            if c_norm == s_norm or c_norm.lower() == s_lower:
                found = i
                break
        if found is None:
            return "subcategory"
        index = found

    boundary = _subcategory_2_start_index()
    if index < boundary:
        return "subcategory"
    return "subcategory_2"


def get_sub_subcategory_metafield_key(label):
    """
    Route a sub-subcategory value to custom.sub_subcategory or custom.sub_subcategory_2.
    Prefers live Shopify choice membership.
    """
    s = str(label).strip()
    if not s:
        return "sub_subcategory"

    ss = fetch_shopify_metafield_definition_choices("custom", "sub_subcategory")
    ss2 = fetch_shopify_metafield_definition_choices("custom", "sub_subcategory_2")
    s_lower = s.lower()

    def _in(choices):
        for choice in choices or []:
            c = str(choice)
            if c == s or c.strip() == s or c.strip().lower() == s_lower:
                return True
        return False

    if _in(ss):
        return "sub_subcategory"
    if _in(ss2):
        return "sub_subcategory_2"
    if ss2 or len(ss or []) >= 120:
        return "sub_subcategory_2"
    return "sub_subcategory"
