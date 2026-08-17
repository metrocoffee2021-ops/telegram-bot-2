# METROPIA COFFEE — Digital Platform V2

This is the consolidated deployment package built on the existing Metropia Coffee Telegram bot.

## Included
- Customer menu, cart, checkout and Telegram payments
- Cash / Click / Payme flows from the existing bot
- Loyalty stamps
- Birthday reward: 50% off one drink, valid 7 days, once per calendar year
- Owner `/admin` menu editor
- Owner `/manager` business manager
- Persistent branch/location management
- Persistent promotion CRUD (percentage/fixed)
- Promo-code checkout support via `/promo CODE`
- Staff order queue and existing order workflow
- Daily sales reporting
- Uzbek / Russian / English customer texts
- Latin-script Uzbek birthday/admin messaging

## Environment
Set these Railway variables:

`BOT_TOKEN`
`OWNER_TELEGRAM_ID`
`STAFF_GROUP_ID` (optional)
`CLICK_PROVIDER_TOKEN` (optional until Click is configured)
`PAYME_PROVIDER_TOKEN` (optional until Payme is configured)

The application loads `.env` before importing admin/handler modules, so owner authorization is consistent at startup.

## Owner commands
- `/admin` — menu/product editor
- `/manager` — business manager
- `/admin_status` — authorization diagnostic
- `/myid` — Telegram ID helper if present in the customer handlers

## Manager
- Locations: add, activate/deactivate, delete
- Promotions: create, activate/deactivate, delete
- Products: opens the existing full `/admin` editor
- Orders: open-order view
- Analytics: today's order/revenue summary
- Birthday: current 50% reward policy

## Promotions
Create a promotion in Manager, activate it, then a customer can enter `/promo CODE`. The active percentage/fixed discount is applied to the current cart at checkout. Birthday discount takes priority and does not stack.

## Important
The web dashboard discussed earlier is not included in this package because the Telegram Manager is the current production control surface. Do not expose an unauthenticated web dashboard publicly.

## SIMPLIFIED CUSTOMER CHECKOUT

The customer side is intentionally short:

1. Open bot → **Order**
2. Choose category → product → options → **Add**
3. Open **Cart** → **Checkout**
4. Returning customer: saved phone + saved branch are reused automatically.
5. Pickup is the default and is **ASAP** by default.
6. Customer goes directly to one payment screen: Click / Payme / Cash.
7. Delivery is optional and only asks for a location when selected.

The bot no longer asks the customer to type their name, write notes, or choose a pickup time during normal checkout. Telegram's profile name is saved automatically, the phone is requested once, and branch selection is remembered.
