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
    {"title": "Chocolate Bar Mini", "parent_child_value": "Parent - Chocolate Bar Mini", "id": 15234705916282},
    {"title": "Chocolate Bar Midi", "parent_child_value": "Parent - Chocolate Bar Midi", "id": 15740569059706},
    {"title": "Chocolate Bar Maxi", "parent_child_value": "Parent - Chocolate Bar Maxi", "id": 15740667199866},
    {"title": "Neo", "parent_child_value": "Parent - Neo", "id": None},
    {"title": "Chunky Milk Chocolate Bar Wrap", "parent_child_value": "Parent - Chunky Milk Chocolate Bar Wrap", "id": 15739539718522},
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

# Category choices for custom.custom_category metafield
CATEGORIES = [
    "All",
    "Latest",
    "Best Sellers",
    "Express",
    "Super Express",
    "Seasonal",
    "Themes",
    "Events & Charities",
    "Brands",
    "Eco",
    "Biscuits, Cakes & Pies",
    "Cereals & Cereal Bars",
    "Chewing Gum",
    "Chocolate",
    "Crisps",
    "Dried Fruits",
    "Drinks",
    "Flapjacks",
    "Honey",
    "Jams, Marmalades & Spreads",
    "Lollipops",
    "Popcorn",
    "Pretzels",
    "Protein",
    "Savoury Snacks",
    "Soup",
    "Sprinkles",
    "Sweets",
    "Mints",
    "Vegan",
    "Packaging",
]

# Subcategory choices for custom.subcategory metafield
# This list is organized hierarchically by category (order matches CATEGORY_MAPPING)
SUBCATEGORIES = [
    # Seasonal
    "Black Friday",
    "Christmas",
    "Easter",
    "Eid",
    "Halloween",
    "New Year",
    "Ramadan",
    "Summer",
    "Valentines Day",
    # Themes
    "Achievement",
    "Anniversary",
    "Appreciation",
    "Awards",
    "Back To School",
    "British",
    "Carnival",
    "Celebrations",
    "Community",
    "Countdown to Launch",
    "Customers",
    "Diversity & Inclusion",
    "Empowerment",
    "Football",
    "Heroes",
    "Ideas",
    "Loyalty",
    "Meet The Team",
    "Mental Health",
    "Milestones",
    "Product Launch",
    "Referral Rewards",
    "Sale",
    "Saver Offers",
    "Staff",
    "Success",
    "Support",
    "Sustainability",
    "Thank You",
    "University",
    "Volunteer",
    "Wellbeing",
    "We Miss You",
    # Events & Charities
    "Cancer Research",
    "Careers Week",
    "Mental Health Awareness",
    "Movember",
    "Pride",
    "Volunteers Week",
    "Wimbledon",
    "World Bee Day",
    "World Blood Donor Day",
    "World Cup - Football",
    "World Cup - Rugby",
    # Brands
    "Cadbury",
    "Haribo",
    "Heinz",
    "Jordans",
    "Kelloggs",
    "Mars",
    "McVities",
    "Nature Valley",
    "Nestle",
    "Swizzels",
    "Walkers",
    # Biscuits, Cakes & Pies
    "Biscuits - Box",
    "Biscuits - Single",
    "Cake - Box",
    "Cake Bars - Single",
    "Cakes - Round",
    "Cakes - Traybake",
    "Cupcakes - Box",
    "Cupcakes - Single",
    "Pies - Box",
    "Pies - Single",
    # Cereals & Cereal Bars
    "Breakfast Cereals",
    "Cereal Bars",
    "Porridge",
    # Chewing Gum
    "Mint",
    # Chocolate
    "Balls",
    "Bars",
    "Coins",
    "Hearts",
    "Neapolitans",
    "Truffles",
    # Dried Fruits
    "Apricots",
    "Bananas",
    "Dates",
    # Drinks
    "Coffee",
    "Soft Drinks",
    "Hot Chocolate",
    "Tea",
    "Water",
    # Jams, Marmalades & Spreads
    "Marmalade",
    "Marmite",
    "Nutella",
    "Jams",
    # Lollipops
    "Chocolate",
    "Sugar",
    # Popcorn
    "Microwave",
    "Popped",
    # Protein
    "Nuts",
    # Savoury Snacks
    "Bags",
    "Packs",
    # Sprinkles
    "Shapes",
    "Vermicelli",
    # Sweets
    "Boiled/Compressed",
    "Jellies",
    # Vegan
    "Sweets",
    "Treats",
    # Packaging
    "Bottle",
    "Card",
    "Card Box - A Box",
    "Card Box - Rectangle",
    "Card Box - Shape",
    "Card Box - Square",
    "Eco",
    "Header Card",
    "Jar",
    "Label",
    "Nets",
    "Organza Bag",
    "Popcorn Box",
    "Plastic Box",
    "Tin",
    "Tub",
    "Wrap",
]

# Overflow boundary: subcategory_2 contains this item and everything after it in SUBCATEGORIES
SUBCATEGORY_2_FIRST_ITEM = "Sweets"

# Category to subcategory mapping
# This dictionary stores which subcategories belong to which categories
# Format: {"Category Name": ["Subcategory1", "Subcategory2", ...]}
CATEGORY_MAPPING = {
    "Seasonal": [
        "Black Friday",
        "Christmas",
        "Easter",
        "Eid",
        "Halloween",
        "New Year",
        "Ramadan",
        "Summer",
        "Valentines Day",
    ],
    "Themes": [
        "Achievement",
        "Anniversary",
        "Appreciation",
        "Awards",
        "Back To School",
        "British",
        "Carnival",
        "Celebrations",
        "Community",
        "Countdown to Launch",
        "Customers",
        "Diversity & Inclusion",
        "Empowerment",
        "Football",
        "Heroes",
        "Ideas",
        "Loyalty",
        "Meet The Team",
        "Mental Health",
        "Milestones",
        "Product Launch",
        "Referral Rewards",
        "Sale",
        "Saver Offers",
        "Staff",
        "Success",
        "Support",
        "Sustainability",
        "Thank You",
        "University",
        "Volunteer",
        "Wellbeing",
        "We Miss You",
    ],
    "Events & Charities": [
        "Cancer Research",
        "Careers Week",
        "Mental Health Awareness",
        "Movember",
        "Pride",
        "Volunteers Week",
        "Wimbledon",
        "World Bee Day",
        "World Blood Donor Day",
        "World Cup - Football",
        "World Cup - Rugby",
    ],
    "Brands": [
        "Cadbury",
        "Haribo",
        "Heinz",
        "Jordans",
        "Kelloggs",
        "Mars",
        "McVities",
        "Nature Valley",
        "Nestle",
        "Swizzels",
        "Walkers",
    ],
    "Biscuits, Cakes & Pies": [
        "Biscuits - Box",
        "Biscuits - Single",
        "Cake - Box",
        "Cake Bars - Single",
        "Cakes - Round",
        "Cakes - Traybake",
        "Cupcakes - Box",
        "Cupcakes - Single",
        "Pies - Box",
        "Pies - Single",
    ],
    "Cereals & Cereal Bars": [
        "Breakfast Cereals",
        "Cereal Bars",
        "Porridge",
    ],
    "Chewing Gum": [
        "Mint",
    ],
    "Chocolate": [
        "Balls",
        "Bars",
        "Coins",
        "Hearts",
        "Neapolitans",
        "Shapes",
        "Truffles",
    ],
    "Dried Fruits": [
        "Apricots",
        "Bananas",
        "Dates",
    ],
    "Drinks": [
        "Coffee",
        "Hot Chocolate",
        "Soft Drinks",
        "Tea",
        "Water",
    ],
    "Jams, Marmalades & Spreads": [
        "Marmalade",
        "Marmite",
        "Nutella",
        "Jams",
    ],
    "Lollipops": [
        "Chocolate",
        "Sugar",
    ],
    "Popcorn": [
        "Microwave",
        "Popped",
    ],
    "Protein": [
        "Bars",
        "Nuts",
    ],
    "Savoury Snacks": [
        "Bags",
        "Bars",
        "Packs",
    ],
    "Sprinkles": [
        "Shapes",
        "Vermicelli",
    ],
    "Sweets": [
        "Boiled/Compressed",
        "Jellies",
    ],
    "Vegan": [
        "Sweets",
        "Treats",
    ],
    "Packaging": [
        "Bags",
        "Bottle",
        "Card",
        "Card Box - A Box",
        "Card Box - Rectangle",
        "Card Box - Shape",
        "Card Box - Square",
        "Eco",
        "Header Card",
        "Jar",
        "Label",
        "Nets",
        "Organza Bag",
        "Popcorn Box",
        "Plastic Box",
        "Tin",
        "Tub",
        "Wrap",
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

def _subcategory_2_start_index():
    """Index in SUBCATEGORIES where subcategory_2 starts (Sweets and everything after)."""
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
