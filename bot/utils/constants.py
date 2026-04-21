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
