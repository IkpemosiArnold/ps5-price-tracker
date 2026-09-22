# PS5 Price Watch

Watches PS Store (US) prices for a list of PS5 games and tells you when one
goes on sale — via email and an in-app banner on a small web page.

**How it works:** a GitHub Action runs on a schedule (every 6 hours by
default), fetches each game's PS Store product page, and checks whether it's
discounted below full price. Results are committed back into this repo and
shown on a GitHub Pages site.

There's no official PS Store price API, so this reads the same page data
your browser gets when you open a product page. It needs no PSN login and
carries no account-ban risk, but Sony could change their page structure at
any time — see the note at the top of `scripts/check_prices.py` if checks
start failing.

## Setup (about 10 minutes)

1. **Create a repo.** On GitHub, create a new repository (public or
   private — private also works with GitHub Pages on a paid plan; public is
   free) and push everything in this folder to it.

2. **Turn on GitHub Pages.**
   Repo → Settings → Pages → Source: "Deploy from a branch" → Branch:
   `main`, folder: `/docs` → Save. Your app will be live at
   `https://<you>.github.io/<repo>/` within a minute or two.

3. **Add your first games.**
   Edit `docs/games.json` — for each game, grab its PS Store URL
   (`https://store.playstation.com/en-us/product/XXXXXXX`) and use the part
   after `/product/` as the `id`. Remove the example entry. Commit.
   (Once Pages is live, you can also add games from the web app itself —
   see step 5.)

4. **Set up email alerts.**
   Repo → Settings → Secrets and variables → Actions → New repository
   secret. Add:
   - `SMTP_USER` — your email address (Gmail works well)
   - `SMTP_PASS` — an [app password](https://myaccount.google.com/apppasswords)
     (not your normal password — Gmail requires this for SMTP)
   - `ALERT_EMAIL` — where alerts should be sent (can be the same address)

   Using a different provider? Also add `SMTP_HOST` / `SMTP_PORT` secrets.

5. **(Optional) Add games from the web app.**
   Open your Pages URL → "Settings" under Add a game → create a
   [fine-grained GitHub token](https://github.com/settings/personal-access-tokens/new)
   scoped to *only this repo*, with **Contents: read and write** permission.
   Paste it in, along with `yourusername/reponame`. Now pasting a PS Store
   link in the app will commit it straight to `games.json`.

6. **Run it once manually.**
   Repo → Actions → "Check PS5 game prices" → Run workflow. Check the logs —
   if a game fails to fetch, double check the `id` you used.

That's it — it'll now check automatically every 6 hours (edit the `cron`
line in `.github/workflows/check-prices.yml` to change the frequency) and
email you the moment something you're tracking goes on sale.

## Notes & limits

- "In-app notification" here means a banner on the web page (and a browser
  notification if you grant permission and keep a tab open) — there's no
  push-notification server, since that needs paid infrastructure. Email is
  the reliable channel.
- In-app text search wasn't included — the PS Store's search isn't
  reliably callable from a browser due to CORS. Pasting the product link is
  the reliable path; if you want real search, the natural upgrade is a tiny
  serverless proxy (e.g. a free Cloudflare Worker) that relays search
  queries — ask if you'd like that built out.
- Be reasonable with the check frequency — this fetches public pages, not
  an API, so keep it to a few times a day per game.
