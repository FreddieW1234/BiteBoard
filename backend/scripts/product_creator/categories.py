"""
Category and Subcategory definitions for product metafields

This file contains the preset choices for the custom metafields:
- custom.custom_category
- custom.subcategory
- custom.parent_child (Parent/Child product types; only one product per Parent - X)

You can easily update these lists by editing this file.
"""

# Parent/Child choices for custom.parent_child metafield (single line text with preset list).
# Only one product can have each "Parent - X" value. "Child - X" can be used by many.
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
    "Parent - Moustache Chocolate Header Bag",
    "Child - Moustache Chocolate Header Bag",
    "Parent - Moustache Chocolate Lollipop",
    "Child - Moustache Chocolate Lollipop",
    "Parent - Shirt Box - Chocolate Bar",
    "Child - Shirt Box - Chocolate Bar",
    "Parent - Mini Cuboid - Two Roses",
    "Child - Mini Cuboid - Two Roses",
    "Parent - Mini Cuboid - Two Heroes",
    "Child - Mini Cuboid - Two Heroes",
    "Parent - Mini Cuboid - Two Celebrations",
    "Child - Mini Cuboid - Two Celebrations",
    "Parent - Mini Cuboid - Two Quality Street",
    "Child - Mini Cuboid - Two Quality Street",
    "Parent - Midi Quad - Roses",
    "Child - Midi Quad - Roses",
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
]

# Create from Parent: list of products that have a Parent type set.
# Use "id" (Shopify product ID from admin URL) when possible so lookup is by ID not name.
# Title is used for display and as fallback when id is missing. Restart the app after editing.
# Add "id": <number> from each product's Shopify admin URL (e.g. .../products/15740667199866). Use None until you have the ID.
PARENT_PRODUCTS = [
    {"title": "Chocolate Bar Mini", "parent_child_value": "Parent - Chocolate Bar Mini", "id": None},
    {"title": "Chocolate Bar Midi", "parent_child_value": "Parent - Chocolate Bar Midi", "id": None},
    {"title": "Chocolate Bar Maxi", "parent_child_value": "Parent - Chocolate Bar Maxi", "id": None},
    {"title": "Neo", "parent_child_value": "Parent - Neo", "id": None},
    {"title": "Chunky Milk Chocolate Bar Wrap", "parent_child_value": "Parent - Chunky Milk Chocolate Bar Wrap", "id": None},
    {"title": "Organza Bag - Mini Chocolate Hearts", "parent_child_value": "Parent - Organza Bag - Mini Chocolate Hearts", "id": None},
    {"title": "Moustache Chocolate Header Bag", "parent_child_value": "Parent - Moustache Chocolate Header Bag", "id": None},
    {"title": "Moustache Chocolate Lollipop", "parent_child_value": "Parent - Moustache Chocolate Lollipop", "id": None},
    {"title": "Shirt Box - Chocolate Bar", "parent_child_value": "Parent - Shirt Box - Chocolate Bar", "id": None},
    {"title": "Mini Cuboid - Two Roses", "parent_child_value": "Parent - Mini Cuboid - Two Roses", "id": None},
    {"title": "Mini Cuboid - Two Heroes", "parent_child_value": "Parent - Mini Cuboid - Two Heroes", "id": None},
    {"title": "Mini Cuboid - Two Celebrations", "parent_child_value": "Parent - Mini Cuboid - Two Celebrations", "id": None},
    {"title": "Mini Cuboid - Two Quality Street", "parent_child_value": "Parent - Mini Cuboid - Two Quality Street", "id": None},
    {"title": "Midi Quad - Roses", "parent_child_value": "Parent - Midi Quad - Roses", "id": None},
    {"title": "Midi Quad - Quality Street", "parent_child_value": "Parent - Midi Quad - Quality Street", "id": None},
    {"title": "Organza Bag - Celebrations", "parent_child_value": "Parent - Organza Bag - Celebrations", "id": None},
    {"title": "Organza Bag - Quality Street", "parent_child_value": "Parent - Organza Bag - Quality Street", "id": None},
    {"title": "Organza Bag - Roses", "parent_child_value": "Parent - Organza Bag - Roses", "id": None},
    {"title": "Organza Bag - Heroes", "parent_child_value": "Parent - Organza Bag - Heroes", "id": None},
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
    "Food & Pastry",
    "Branded Merchandise & Packaging",
]

# Subcategory choices for custom.subcategory metafield
# This list is the flat (de-duplicated) set of all subcategories, organized by category
# (order matches CATEGORY_MAPPING). "Lollipops" is shared by Chocolate and Sweets, so it
# appears once here but is mapped to both categories in CATEGORY_MAPPING.
SUBCATEGORIES = [
    # Chocolate
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
    # Food & Pastry
    "Cereal & Porridge",
    "Soup",
    "Pasta & Noodles",
    "Rice & Grains",
    "Desserts",
    "Baking Kits",
    "Spreads, Jams and Condiments",
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

# Category to subcategory mapping
# This dictionary stores which subcategories belong to which categories
# Format: {"Category Name": ["Subcategory1", "Subcategory2", ...]}
CATEGORY_MAPPING = {
    "Chocolate": [
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
    "Food & Pastry": [
        "Cereal & Porridge",
        "Soup",
        "Pasta & Noodles",
        "Rice & Grains",
        "Desserts",
        "Baking Kits",
        "Spreads, Jams and Condiments",
        "Herbs, Spices & Seasonings",
        "Ice & Freeze Pops",
    ],
    "Branded Merchandise & Packaging": [
        "Packaging",
        "Merchandise",
        "Fulfillment Service",
    ],
}

def get_category_choices():
    """
    Get the list of available category choices
    
    Returns:
        list: List of category choices
    """
    return CATEGORIES.copy()

def get_subcategory_choices():
    """
    Get the list of available subcategory choices
    
    Returns:
        list: List of subcategory choices
    """
    return SUBCATEGORIES.copy()

def get_category_subcategory_groups():
    """
    Get categories with their subcategories for the combined Category & Subcategory dropdown.

    Each category is shown as a bold, non-selectable heading; its subcategories are the
    selectable options. Selecting a subcategory implies (and saves) its parent category.
    Note: a subcategory may appear under more than one category (e.g. "Lollipops" under
    both Chocolate and Sweets) - it is listed under each.

    Returns:
        list: List of {category, subcategories} dicts (in CATEGORY_MAPPING order)
    """
    return [
        {"category": cat, "subcategories": list(subs)}
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
        # Everything before "Sweets"
        idx = _subcategory_2_start_index()
        return SUBCATEGORIES[:idx]
    elif metafield_key == "subcategory_2":
        # "Sweets" and everything after
        idx = _subcategory_2_start_index()
        return SUBCATEGORIES[idx:]
    elif metafield_key.startswith("subcategory_"):
        # subcategory_3, etc. - not used currently; keep slice by 128 for future
        try:
            chunk_index = int(metafield_key.split("_")[-1]) - 1
            start_idx = chunk_index * 128
            end_idx = start_idx + 128
            return SUBCATEGORIES[start_idx:end_idx]
        except (ValueError, IndexError):
            return []
    elif metafield_key == "parent_child":
        return list(PARENT_CHILD_CHOICES)
    else:
        # Filter group metafields (custom.packaging, custom.size, custom.brand, custom.eco)
        for group in FILTER_GROUPS:
            if group["key"] == metafield_key:
                return list(group["options"])
        return []

def get_subcategory_metafield_key(subcategory):
    """
    Determine which metafield key should be used for a given subcategory.
    subcategory = everything before "Sweets"; subcategory_2 = "Sweets" and everything after.
    """
    s = str(subcategory).strip()
    if not s:
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
