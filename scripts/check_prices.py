#!/usr/bin/env python3
"""
Checks PS Store (US) prices for every game in docs/games.json, compares
against the last known price in docs/data/state.json, and:
  - updates docs/data/state.json with the latest price info
  - updates docs/data/notifications.json (read by the web app for the
    in-app "active discounts" banner)
  - emails you (via SMTP) when a game goes on sale for the first time
    since the last check

NOTE ON RELIABILITY: the PlayStation Store has no official public price
API. This script reads the same embedded JSON data (__NEXT_DATA__) that
store.playstation.com sends to your browser when you load a product page.
Sony can change that page's structure at any time without notice. The
parser below searches recursively for a price-shaped object rather than
a fixed path, to be more resilient to small changes, but if Sony ships a
redesign this script may need an update. If every game starts showing
"price lookup failed" in the Action logs, that's the most likely cause.
"""

import json
import os
import re
import smtplib
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
GAMES_FILE = ROOT / "docs" / "games.json"
STATE_FILE = ROOT / "docs" / "data" / "state.json"
NOTIFICATIONS_FILE = ROOT / "docs" / "data" / "notifications.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

PRODUCT_URL = "https://store.playstation.com/en-us/product/{id}"


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return default
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def find_price_block(node):
    """Recursively search a parsed JSON tree for the first dict that
    looks like a PS Store price object, i.e. has both a base price and
    a discounted/current price in cents."""
    if isinstance(node, dict):
        keys = {k.lower() for k in node.keys()}
        if {"discountedprice", "baseprice"} <= keys or {
            "discountedvalue",
            "basevalue",
        } <= keys:
            return node
        for v in node.values():
            found = find_price_block(v)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_price_block(item)
            if found:
                return found
    return None


def get_value(block, *candidates):
    for c in candidates:
        for k in block:
            if k.lower() == c.lower():
                return block[k]
    return None


def fetch_price(game_id):
    url = PRODUCT_URL.format(id=game_id)
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        resp.text,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError("Could not find embedded page data (__NEXT_DATA__)")

    data = json.loads(match.group(1))
    block = find_price_block(data)
    if not block:
        raise RuntimeError("Could not locate a price block in page data")

    base_cents = get_value(block, "baseprice", "basevalue")
    disc_cents = get_value(block, "discountedprice", "discountedvalue")
    discount_pct = get_value(block, "discounttext", "discountpercentage")
    currency = get_value(block, "currency") or "USD"

    if base_cents is None or disc_cents is None:
        raise RuntimeError("Price fields present but empty")

    return {
        "base_price": round(base_cents / 100, 2)
        if isinstance(base_cents, (int, float)) and base_cents > 1000
        else base_cents,
        "current_price": round(disc_cents / 100, 2)
        if isinstance(disc_cents, (int, float)) and disc_cents > 1000
        else disc_cents,
        "discount_pct": discount_pct,
        "currency": currency,
        "url": url,
    }


def send_email(subject, body):
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    to_addr = os.environ.get("ALERT_EMAIL")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    if not all([smtp_user, smtp_pass, to_addr]):
        print("Email secrets not set (SMTP_USER / SMTP_PASS / ALERT_EMAIL) — skipping email.")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_addr

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to_addr], msg.as_string())
    print(f"Email sent to {to_addr}")


def main():
    games = load_json(GAMES_FILE, [])
    state = load_json(STATE_FILE, {})

    active_discounts = []
    new_alerts = []
    email_lines = []

    for game in games:
        game_id = game.get("id")
        name = game.get("name", game_id)
        if not game_id or game_id.startswith("UP9000-PPSA01858_00-GOWRDIGITALDELUXE") and name.startswith("Example"):
            # skip the placeholder example entry
            continue

        print(f"Checking {name} ...")
        try:
            price_info = fetch_price(game_id)
        except Exception as exc:  # noqa: BLE001
            print(f"  Failed: {exc}")
            continue

        is_discounted = (
            price_info["current_price"] is not None
            and price_info["base_price"] is not None
            and price_info["current_price"] < price_info["base_price"]
        )

        prev = state.get(game_id, {})
        was_discounted = prev.get("is_discounted", False)
        price_dropped_further = (
            is_discounted
            and prev.get("current_price") is not None
            and price_info["current_price"] < prev["current_price"]
        )

        if is_discounted and (not was_discounted or price_dropped_further):
            new_alerts.append({"name": name, **price_info})
            email_lines.append(
                f"- {name}: was ${price_info['base_price']}, now "
                f"${price_info['current_price']} ({price_info.get('discount_pct') or ''}) "
                f"-> {price_info['url']}"
            )

        if is_discounted:
            active_discounts.append({"name": name, **price_info})

        state[game_id] = {**price_info, "is_discounted": is_discounted, "name": name}
        time.sleep(2)  # be polite to Sony's servers

    save_json(STATE_FILE, state)
    save_json(
        NOTIFICATIONS_FILE,
        {
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "active_discounts": active_discounts,
            "recent_alerts": new_alerts,
        },
    )

    if new_alerts:
        body = "New PS5 discounts found:\n\n" + "\n".join(email_lines)
        send_email(f"{len(new_alerts)} new PS5 discount(s)!", body)
    else:
        print("No new discounts this run.")


if __name__ == "__main__":
    main()
