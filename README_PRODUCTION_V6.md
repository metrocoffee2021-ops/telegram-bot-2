# Metropia Coffee — Production V6

## What was fixed

- Simplified customer checkout remains: saved profile/branch, only request missing information.
- Cart is persisted in SQLite and restored after a bot restart.
- Birthday reward: 50% off one birthday-eligible drink, once per calendar year, configurable validity.
- Real calendar validation for birthdays, including invalid dates.
- Birthday reward is issued immediately if a customer registers their birthday on the birthday itself.
- Birthday eligibility is stored on menu items; obvious dessert categories are excluded automatically.
- Payment provider configuration is validated before creating an order.
- Cash checkout clears the persisted cart immediately after the order is placed.
- Click/Payme/bundle successful flows clear the persisted cart after confirmation.
- Promotions support active/inactive state, percentage/fixed discounts, start/end time, minimum subtotal and maximum uses.
- Promotion usage is recorded after successful payment.
- Branches support phone, opening hours, pickup and delivery flags in addition to address/coordinates.
- Manager supports branch and promotion CRUD, product editor access, order workflow and 1/7/30-day analytics.
- Manager can move orders NEW → PREPARING → READY → COMPLETED and sends a customer-ready notification.
- Owner authorization is centralized through config.py.
- Uzbek text block contains no Cyrillic characters.

## Important deployment variables

BOT_TOKEN=...
OWNER_TELEGRAM_ID=...
STAFF_GROUP_ID=...
CLICK_PROVIDER_TOKEN=...
PAYME_PROVIDER_TOKEN=...

Only provider tokens that are configured are offered to customers.

## Customer flow

HOME → ORDER → CATEGORY → PRODUCT → CUSTOMIZE → ADD → CART → CHECKOUT → PAYMENT

Returning customers reuse their saved phone and branch.

## Manager

Send `/manager` as the configured owner.

Locations:
- add/edit/activate/deactivate/delete
- phone, hours, pickup and delivery settings

Promotions:
- create/edit/activate/deactivate/delete
- percent/fixed
- start/end
- minimum subtotal
- usage limit

Orders:
- prepare
- ready
- complete
- cancel

Analytics:
- today
- last 7 days
- last 30 days

Birthday:
- discount percent
- validity days
- one drink
- once per calendar year
