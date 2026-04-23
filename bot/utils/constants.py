SUPPORTED_CURRENCIES = {
    "SGD", "USD", "EUR", "GBP", "JPY", "KRW",
    "MYR", "THB", "IDR", "AUD", "CNY", "TWD",
    "HKD", "PHP", "VND",
}

CATEGORIES = [
    "food",
    "transport",
    "accommodation",
    "sightseeing",
    "activities",
    "groceries",
    "flight",
    "others",
]

CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "food": {
        # Meal types
        "dinner", "lunch", "breakfast", "brunch", "supper", "meal", "snack",
        # Venues
        "restaurant", "hawker", "cafe", "cafeteria", "bistro", "diner", "eatery",
        "foodcourt", "canteen", "kopitiam", "izakaya", "tavern", "pub", "bar", "lounge",
        # Drinks
        "coffee", "tea", "boba", "bubble", "drink", "drinks", "beer", "wine",
        "cocktail", "juice", "smoothie", "milkshake", "sake", "soju",
        # Cuisines / dishes
        "noodles", "ramen", "udon", "soba", "pho", "laksa", "pasta", "rice",
        "pizza", "burger", "sushi", "sashimi", "tempura", "yakitori", "gyoza",
        "dumpling", "dumplings", "dimsum", "hotpot", "steamboat",
        "bbq", "barbecue", "grill", "steak", "ribs",
        "curry", "tandoori", "naan", "biryani", "satay", "rendang",
        "tacos", "burrito", "kebab", "shawarma", "falafel",
        "soup", "salad", "sandwich", "wrap", "bagel", "croissant",
        "dessert", "cake", "gelato", "waffle", "pancake",
        "donut", "doughnut", "pastry", "crepe", "mochi", "matcha",
        "toast", "bread", "bakery",
        # Proteins
        "chicken", "pork", "beef", "lamb", "fish", "seafood", "prawn", "crab",
        "lobster", "oyster", "salmon", "tuna",
        # Chains
        "mcdonald", "mcdonalds", "kfc", "subway", "starbucks", "jollibee",
        "yoshinoya", "sukiya",
        # Actions
        "food", "eat", "eating", "ate", "dine", "dining",
        "takeaway", "takeout", "delivery", "dabao",
        # Buffet
        "buffet",
    },
    "transport": {
        # Rideshare / taxi
        "taxi", "cab", "grab", "uber", "lyft", "gojek", "bolt", "didi", "ride", "carpool",
        # Public transit
        "bus", "train", "mrt", "subway", "metro", "tram", "monorail", "ferry", "boat",
        "ezlink", "suica", "pasmo", "icoca", "octopus", "transit", "fare",
        # Driving
        "toll", "parking", "gas", "petrol", "fuel", "diesel",
        "rental",
        # Two-wheelers
        "tuktuk", "scooter", "motorbike", "motorcycle", "bike", "bicycle", "cycling",
        # Top-up
        "topup", "reload",
        # General
        "transport", "transportation", "commute", "highway", "expressway",
        # Specific
        "shinkansen", "rickshaw", "songthaew", "jeepney",
    },
    "accommodation": {
        # Venue types
        "hotel", "hostel", "airbnb", "resort", "motel", "inn", "lodge",
        "guesthouse", "bnb", "pension", "ryokan", "minshuku", "capsule",
        "villa", "apartment", "condo", "serviced", "homestay", "dormitory", "dorm",
        # Actions
        "stay", "staying", "checkin", "checkout", "accommodation", "lodging",
        "reservation",
        # Related
        "suite", "night", "nights", "nightly", "laundry",
        # Platforms
        "agoda", "expedia",
    },
    "sightseeing": {
        # Attractions
        "museum", "temple", "shrine", "church", "mosque", "cathedral",
        "palace", "castle", "fortress", "fort", "ruins",
        "tower", "observatory", "monument", "memorial", "statue", "landmark",
        "gallery", "exhibition", "exhibit",
        # Nature
        "park", "garden", "botanical", "waterfall",
        "lake", "mountain", "volcano",
        # Animals
        "zoo", "aquarium", "safari", "wildlife", "sanctuary",
        # General
        "tour", "sightseeing", "attraction", "viewpoint", "scenic",
        "ticket", "entrance", "admission", "pass",
        "heritage", "historic", "historical", "cultural",
        # Specific
        "disneyland", "disney", "universal", "sentosa",
    },
    "activities": {
        # Wellness
        "spa", "massage", "sauna", "onsen", "facial", "manicure", "pedicure", "nail",
        # Sports / outdoor
        "gym", "fitness", "yoga", "pilates",
        "diving", "scuba", "snorkeling", "snorkel",
        "kayak", "kayaking", "canoe", "canoeing", "paddleboard",
        "surf", "surfing", "wakeboard", "jetski",
        "ski", "skiing", "snowboard", "snowboarding",
        "climbing", "bouldering", "hiking", "trekking", "trek",
        "rafting", "zipline", "bungee", "paragliding",
        "golf", "tennis", "badminton", "swimming",
        # Entertainment
        "concert", "show", "performance", "theatre", "theater",
        "movie", "cinema", "film",
        "karaoke", "ktv", "noraebang",
        "arcade", "gaming", "bowling", "escape",
        "amusement", "waterpark",
        "gokart",
        # Classes
        "lesson", "class", "workshop", "pottery", "experience", "activity", "activities",
        # Nightlife
        "club", "nightclub", "dancing", "disco",
    },
    "groceries": {
        # Store types
        "supermarket", "grocery", "groceries", "mart", "hypermart",
        "minimart", "convenience", "konbini", "combini", "market",
        # Chains
        "7eleven", "fairprice", "ntuc", "giant", "shengsiong",
        "donki", "daiso", "lawson", "familymart",
        "walmart", "costco", "aldi", "lidl",
        # Items
        "water", "supplies", "ingredients", "fruit", "fruits",
        "vegetable", "vegetables", "medicine", "pharmacy", "drugstore",
        "toiletries", "shampoo", "soap", "toothpaste",
        "souvenir", "souvenirs", "omiyage", "gift", "gifts",
        "shopping", "bought",
    },
    "flight": {
        "flight", "flights", "airfare",
        "airport", "airline", "airlines",
        "plane", "airplane", "aeroplane",
        "boarding", "terminal", "gate", "departure", "arrival",
        "baggage", "luggage", "carryon",
        "lounge",
        # Airlines
        "jetstar", "scoot", "airasia", "sia",
        "cathay", "ana", "jal", "emirates", "qatar",
        # Related
        "layover", "stopover", "upgrade",
    },
}


def infer_category(description: str) -> str:
    """Infer expense category from description keywords. Returns 'others' if no match."""
    words = set(description.lower().split())
    best_cat = "others"
    best_count = 0
    for cat in CATEGORIES:
        keywords = CATEGORY_KEYWORDS.get(cat, set())
        count = len(words & keywords)
        if count > best_count:
            best_count = count
            best_cat = cat
    return best_cat

CATEGORY_EMOJIS = {
    "food": "🍜",
    "transport": "🚌",
    "accommodation": "🏨",
    "sightseeing": "🗺️",
    "activities": "🎯",
    "groceries": "🛒",
    "flight": "✈️",
    "others": "📦",
}

CONVERSATION_TIMEOUT = 300  # 5 minutes in seconds

# Maps each supported currency to the primary timezone of its travel destination.
# Multi-timezone currencies use the most common tourist hub:
#   USD → New York (US East Coast)
#   EUR → Paris   (Western Europe)
#   AUD → Sydney  (Australia East Coast)
#   IDR → Jakarta (West Indonesia / Java)
CURRENCY_TIMEZONES: dict[str, str] = {
    "SGD": "Asia/Singapore",
    "JPY": "Asia/Tokyo",
    "KRW": "Asia/Seoul",
    "MYR": "Asia/Kuala_Lumpur",
    "THB": "Asia/Bangkok",
    "IDR": "Asia/Jakarta",
    "CNY": "Asia/Shanghai",
    "TWD": "Asia/Taipei",
    "HKD": "Asia/Hong_Kong",
    "PHP": "Asia/Manila",
    "VND": "Asia/Ho_Chi_Minh",
    "AUD": "Australia/Sydney",
    "GBP": "Europe/London",
    "EUR": "Europe/Paris",
    "USD": "America/New_York",
}

RATE_LIMIT_MAX_ATTEMPTS = 3
RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour
