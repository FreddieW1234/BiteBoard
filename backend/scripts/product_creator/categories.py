"""
Category and Subcategory definitions for product metafields

This file contains the preset choices for the custom metafields:
- custom.custom_category
- custom.subcategory
- custom.parent_child (Parent/Child product types; only one product per Parent - X)
- custom.parent_child2 (overflow when parent_child hits Shopify's choice-list limit)

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
]

# Overflow boundary: parent_child2 contains this item and everything after it in PARENT_CHILD_CHOICES.
# Shopify limits choice lists to 128 options (~64 families); parent_child2 continues the same list.
PARENT_CHILD2_FIRST_ITEM = "Parent - Jelly Bears Mini A Box"

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
    "Favourites",
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
    # Favourites
    "Favourites",
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
    "Favourites": [
        "Favourites",
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

def _parent_child_2_start_index():
    """Index in PARENT_CHILD_CHOICES where parent_child2 starts."""
    if not PARENT_CHILD2_FIRST_ITEM:
        return len(PARENT_CHILD_CHOICES)
    try:
        return PARENT_CHILD_CHOICES.index(PARENT_CHILD2_FIRST_ITEM)
    except ValueError:
        return len(PARENT_CHILD_CHOICES)


def get_parent_child_choices():
    """Full merged Parent/Child choice list (parent_child + parent_child2)."""
    return list(PARENT_CHILD_CHOICES)


def get_parent_child_metafield_key(parent_child_value):
    """
    Route a Parent/Child value to parent_child or parent_child2 (overflow metafield).
    Both keys are treated as one logical field in the app.
    """
    val = str(parent_child_value or "").strip()
    if not val:
        return "parent_child"
    boundary = _parent_child_2_start_index()
    try:
        index = PARENT_CHILD_CHOICES.index(val)
    except ValueError:
        val_lower = val.lower()
        index = None
        for i, choice in enumerate(PARENT_CHILD_CHOICES):
            if str(choice).strip().lower() == val_lower:
                index = i
                break
        if index is None:
            return "parent_child2" if boundary < len(PARENT_CHILD_CHOICES) else "parent_child"
    if index < boundary:
        return "parent_child"
    return "parent_child2"


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
        boundary = _parent_child_2_start_index()
        return PARENT_CHILD_CHOICES[:boundary]
    elif metafield_key == "parent_child2":
        boundary = _parent_child_2_start_index()
        return PARENT_CHILD_CHOICES[boundary:]
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
