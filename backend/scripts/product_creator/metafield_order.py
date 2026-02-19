# Metafield Order Configuration
# This file defines the default order for metafields in Field Finder and Product Creator

# Default metafield order based on user preference
# This order will be applied when no custom order is saved in localStorage
DEFAULT_METAFIELD_ORDER = [
    "sku",
    "custom_category", 
    "subcategory",
    "description",
    "moq",
    "origination",
    "shelf_life",
    "unit_weight",
    "case_quantity",
    "case_weight",
    "print_info",
    "recycle_info",
    "ingredients",
    "nutritional_info",
    "leadtime1",
    "leadtime2",
    "whats_inside",
    "vegan",
    "vegetarian",
    "halal",
    "coeliac",
    "peanuts",
    "tree_nuts",
    "sesame",
    "milk",
    "egg",
    "cereals",
    "soya",
    "product_size",
    "commodity_code"
]

# Alternative ordering options (can be used for different views)
ALTERNATIVE_ORDERS = {
    "alphabetical": sorted(DEFAULT_METAFIELD_ORDER),
    "by_type": [
        # Product Info
        "sku", "custom_category", "subcategory", "description",
        # Quantities & Weights
        "moq", "unit_weight", "case_quantity", "case_weight",
        # Logistics
        "origination", "shelf_life", "leadtime1", "leadtime2",
        # Content
        "ingredients", "nutritional_info", "whats_inside", "print_info", "recycle_info",
        # Dietary Info
        "vegan", "vegetarian", "halal", "coeliac", "peanuts", "tree_nuts", "sesame", "milk", "egg", "cereals", "soya",
        # Additional Fields
        "product_size", "commodity_code"
    ],
    "priority": [
        # High Priority
        "sku", "custom_category", "subcategory", "description", "moq",
        # Medium Priority  
        "unit_weight", "case_weight", "case_quantity", "origination", "shelf_life",
        # Lower Priority
        "vegan", "vegetarian", "halal", "coeliac", "peanuts", "tree_nuts", "sesame", "milk", "egg", "cereals", "soya",
        "ingredients", "nutritional_info", "whats_inside", "print_info", "recycle_info", "leadtime1", "leadtime2",
        "product_size", "commodity_code"
    ]
}

def get_default_order():
    """Returns the default metafield order"""
    return DEFAULT_METAFIELD_ORDER.copy()

def get_order_by_name(order_name):
    """Returns a specific order by name, falls back to default if not found"""
    return ALTERNATIVE_ORDERS.get(order_name, DEFAULT_METAFIELD_ORDER.copy())

def get_available_orders():
    """Returns a list of available order names"""
    return ["default"] + list(ALTERNATIVE_ORDERS.keys())

# Pricing Table Quantity Bands
# Format: Each tuple is (min_qty, max_qty)
# Used for the "Qty Autofill" button in the pricing tables
PRICING_QTY_BANDS = [
    (100, 250),
    (300, 500),
    (550, 1000),
    (1050, 2500),
    (2550, 5000),
    (5050, 10000)
]

def get_pricing_qty_bands():
    """Returns the pricing quantity bands for autofill"""
    return PRICING_QTY_BANDS.copy()

# Foil Colours Configuration
# Format: Each tuple is (colour_name, colour_code)
# Used for the "All foil colours" button in the colour options
FOIL_COLOURS = [
    ("Black", "b"),
    ("Cerise", "c"),
    ("Gold", "g"),
    ("Green", "gr"),
    ("Orange", "o"),
    ("Pink", "p"),
    ("Purple", "pu"),
    ("Red", "r"),
    ("Silver", "s"),
    ("Turquoise", "tq")
]

def get_foil_colours():
    """Returns the foil colours for autofill"""
    return FOIL_COLOURS.copy()