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

RATE_LIMIT_MAX_ATTEMPTS = 3
RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour
