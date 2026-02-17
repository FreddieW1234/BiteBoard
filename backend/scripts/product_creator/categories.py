"""
Category and Subcategory definitions for product metafields

This file contains the preset choices for the custom metafields:
- custom.custom_category
- custom.subcategory

You can easily update these lists by editing this file.
"""

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
    "Single Shapes",
    "Truffles",
    # Dried Fruits
    "Apricots",
    "Bananas",
    "Dates",
    # Drinks
    "Coffee",
    "Fizzy",
    "Hot Chocolate",
    "Still",
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
        "Single Shapes",
        "Truffles",
    ],
    "Dried Fruits": [
        "Apricots",
        "Bananas",
        "Dates",
    ],
    "Drinks": [
        "Coffee",
        "Fizzy",
        "Hot Chocolate",
        "Still",
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
