# METROPIA COFFEE — DIGITAL PLATFORM V2

This package is an additive upgrade to the existing aiogram/SQLite bot.

## Included
- Existing customer menu, cart, checkout, Click/Payme and cash flows preserved
- Existing loyalty/stamps preserved
- Existing owner /admin and staff queue preserved
- New migration-safe business layer: `metropia_v2.py`
- New owner manager router: `manager.py`
- New lightweight web manager dashboard: `web_dashboard.py`
- Metropia UI rules: `BRAND_UI.md`
- Uzbek Latin validation script: `validate_uzbek_latin.py`

## Environment additions
`METROPIA_DASHBOARD=1` enables the dashboard thread. On Railway, the app can use the platform `PORT` variable.

## Security
The dashboard is intentionally lightweight and should be protected behind Railway/private networking or a reverse proxy before public production use. Do not expose it directly to the internet without authentication.
