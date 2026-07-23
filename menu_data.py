# menu_data.py
# SEED DATA ONLY. This file is used exactly once — the first time the bot ever
# runs — to fill the database with your starting menu. After that, every
# change (add a drink, change a price, remove something) is done from inside
# Telegram using the /admin command. Editing this file after the first run
# has no effect, since the real menu lives in metropia.db from then on.

SEED_CATEGORIES = [
    # (category_id, name_uz, name_ru, name_en)
    ("qahvalar", "Qahvalar", "Кофе", "Coffee"),
    ("matcha", "Matcha", "Матча", "Matcha"),
    ("soda", "Soda", "Сода", "Soda"),
]

# Each item: (category_id, item_key, name_uz, name_ru, name_en, has_topping_option, variants)
# variants: list of (temp, size, price) — size is None for single-size items.
SEED_ITEMS = [
    ("qahvalar", "espresso", "Espresso", "Эспрессо", "Espresso", False, [
        ("issiq", None, 20000),
    ]),
    ("qahvalar", "amerikano", "Amerikano", "Американо", "Americano", False, [
        ("issiq", "M", 20000), ("issiq", "L", 25000),
        ("sovuq", "M", 20000), ("sovuq", "L", 25000),
    ]),
    ("qahvalar", "latte", "Latte", "Латте", "Latte", False, [
        ("issiq", "M", 25000), ("issiq", "L", 30000),
        ("sovuq", "M", 30000), ("sovuq", "L", 35000),
    ]),
    ("qahvalar", "kappuchino", "Kappuchino", "Капучино", "Cappuccino", False, [
        ("issiq", "M", 25000), ("issiq", "L", 30000),
        ("sovuq", "M", 30000), ("sovuq", "L", 35000),
    ]),
    ("qahvalar", "moka", "Mo'ka", "Мокка", "Mocha", False, [
        ("issiq", "M", 35000), ("issiq", "L", 40000),
    ]),
    ("qahvalar", "karamel_makiato", "Karamel Makiato", "Карамель Макиато", "Caramel Macchiato", False, [
        ("issiq", "M", 30000), ("issiq", "L", 35000),
        ("sovuq", "M", 30000), ("sovuq", "L", 35000),
    ]),
    ("qahvalar", "frappuchino", "Frappuchino", "Фраппучино", "Frappuccino", False, [
        ("sovuq", "M", 35000), ("sovuq", "L", 40000),
    ]),
    ("qahvalar", "ananas_bambl", "Ananas Bambl", "Ананас Бамбл", "Pineapple Bramble", False, [
        ("sovuq", "M", 30000), ("sovuq", "L", 35000),
    ]),
    ("qahvalar", "issiq_shokolad", "Issiq Shokolad", "Горячий шоколад", "Hot Chocolate", False, [
        ("issiq", "M", 25000), ("issiq", "L", 30000),
    ]),
    ("qahvalar", "kokos_latte", "Kokos Latte", "Кокосовый латте", "Coconut Latte", False, [
        ("sovuq", "M", 30000), ("sovuq", "L", 35000),
    ]),
    ("matcha", "matcha", "Matcha", "Матча", "Matcha", False, [
        ("issiq", "M", 30000), ("issiq", "L", 35000),
        ("sovuq", "M", 35000), ("sovuq", "L", 40000),
    ]),
    ("matcha", "matcha_mango", "Matcha Mango", "Матча Манго", "Matcha Mango", False, [
        ("issiq", "M", 35000), ("issiq", "L", 40000),
        ("sovuq", "M", 35000), ("sovuq", "L", 40000),
    ]),
    ("matcha", "matcha_qulupnay", "Matcha Qulupnay", "Матча Клубника", "Matcha Strawberry", False, [
        ("issiq", "M", 35000), ("issiq", "L", 40000),
        ("sovuq", "M", 35000), ("sovuq", "L", 40000),
    ]),
    ("matcha", "matcha_smuzi", "Matcha Smuzi", "Матча Смузи", "Matcha Smoothie", False, [
        ("sovuq", "M", 35000), ("sovuq", "L", 40000),
    ]),
    ("matcha", "matcha_blueberry", "Matcha Blueberry", "Матча Черника", "Matcha Blueberry", False, [
        ("issiq", "M", 35000), ("issiq", "L", 40000),
        ("sovuq", "M", 35000), ("sovuq", "L", 40000),
    ]),
    ("soda", "limon", "Limon", "Лимон", "Lemon", False, [
        ("sovuq", "M", 25000), ("sovuq", "L", 30000),
    ]),
    ("soda", "marakuya", "Marakuya", "Маракуйя", "Passion Fruit", False, [
        ("sovuq", "M", 30000), ("sovuq", "L", 35000),
    ]),
    ("soda", "moxito", "Moxito", "Мохито", "Mojito", False, [
        ("sovuq", "M", 25000), ("sovuq", "L", 30000),
    ]),
    ("soda", "kivi", "Kivi", "Киви", "Kiwi", False, [
        ("sovuq", "M", 30000), ("sovuq", "L", 35000),
    ]),
]

# Flat add-on price for extras (e.g. boba toppings) — offered on any item an
# admin marks as "has topping option" when adding/editing it in /admin.
EXTRA_TOPPING_PRICE = 10000
