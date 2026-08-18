# Setting up your Metropia Coffee bot — step by step

You don't need to understand any of the code below. Just follow these steps in order.

## 1. Get a fresh bot token

Since your old token was shared in chat earlier, revoke it and get a new one:

1. Open Telegram, message **@BotFather**
2. Send `/mybots` → tap **Metropia_bot** → **API Token** → **Revoke current token**
3. BotFather gives you a new token — a long string of letters and numbers

## 2. Fill in your settings file

1. Open the file called `.env.example` in the files I gave you
2. Paste your new bot token after `BOT_TOKEN=`
3. Get your own Telegram ID: message **@userinfobot** on Telegram, it replies with a number — paste that after `OWNER_TELEGRAM_ID=` (this is what lets only you send promo broadcasts and use `/admin`)
4. Rename the file from `.env.example` to `.env` (just remove the `.example` part)

Leave the `CLICK_PROVIDER_TOKEN` and `PAYME_PROVIDER_TOKEN` lines empty for now — the bot will work for menu browsing and ordering without them, you'll just add them once you've connected each provider (step 4).

## 3. Choose where the bot runs

A bot needs to run somewhere 24/7 — your own computer being on all the time works, but most shops use a small hosting service instead. The easiest option for someone not comfortable with code is **Railway** (railway.app):

1. Sign up at railway.app (you can use your Google account)
2. Click "New Project" → "Deploy from GitHub repo" — or, simpler, look for "Empty Project" and use their file upload option to upload all the bot files I gave you
3. In the project settings, find "Variables" and add each line from your `.env` file there (same names, same values)
4. Railway will start the bot automatically once the files are uploaded

If this feels like too much on your own, it's completely reasonable to ask a local freelancer to do just this hosting step for you — the bot code itself is already done, they'd just be uploading files to a hosting account.

## 4. Set up Click and Payme payments — both through BotFather

Good news: both providers are connected the same simple way, directly through Telegram, and customers pay right inside the chat — no separate merchant website checkout.

1. Open Telegram, message **@BotFather**
2. Send `/mybots` → tap **Metropia_bot** → **Payments**
3. Tap **Click** (or search for it in the provider list) → follow BotFather's steps to connect your Click business account — it ends with BotFather giving you a token that looks like `333605228:LIVE:15583_xxxxxxxxxxxxx`
4. Paste that token into your `.env` file after `CLICK_PROVIDER_TOKEN=`
5. Repeat the same steps for **Payme** → paste that token after `PAYME_PROVIDER_TOKEN=`
6. Restart the bot (see step 6)

You don't need both ready before launching. The checkout only shows a provider when its token is configured; **Cash** is always available.

## 5. Test it yourself

1. Open Telegram, message your bot
2. Send `/start` → pick a language → tap **Menu**
3. Add a drink to your cart, tap **Checkout**
4. Pick Click or Payme — Telegram's own payment screen will open right in the chat, no phone number needed

## 6. Restart the bot after any change

Any time you update a setting or I send you new files, the bot needs to be restarted to notice the change:
- On Railway: it usually restarts automatically after you update files or variables — if not, there's a "Restart" button in the project dashboard
- On your own computer: stop it (Ctrl+C in the window running it) and run it again

## 7. Managing your menu — no coding, ever

Send `/admin` to your bot (only works from your own Telegram account, since that's the one in `OWNER_TELEGRAM_ID`). From there you can:
- Add a new section (like bringing back Bubble Tea later)
- Add a new drink, with hot/iced and size options, entirely by tapping buttons and typing prices when asked
- Tap any price to change it
- Rename a drink or section
- Turn the "add boba topping" option on or off per drink
- Remove a price option or delete a drink/section entirely

Everything you do in `/admin` takes effect immediately — no file changes, no restarting the bot needed.

If anything looks wrong at any point, just tell me what you saw and I'll fix it.
