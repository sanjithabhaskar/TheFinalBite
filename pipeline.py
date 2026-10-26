"""
Restaurant menu pipeline for the group-dining app.

  python pipeline.py init-db
  python pipeline.py seed "East Village" "Williamsburg" "Midtown East"
  python pipeline.py menus --limit 25
  python pipeline.py report
  python pipeline.py menu-url "Noodle Bar" https://example.com/the-menu   (fix a stubborn one by hand)

Steps:
  seed   -> Google Places (New) text search per neighborhood -> restaurants table
  menus  -> find menu link on each restaurant's website -> an LLM (Gemini by default) extracts items/prices -> menu_items table
  report -> quick sanity check of what you've collected
"""
import argparse
import base64
import json
import os
import re
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urljoin, urlparse

import httpx
import psycopg
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

GOOGLE_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")
PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()   # "gemini" (free tier) or "claude"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
# Free Gemini tier allows only a handful of requests/minute; claude can go faster
MIN_SECONDS_BETWEEN_CALLS = float(os.environ.get("LLM_MIN_SECONDS", "6" if PROVIDER == "gemini" else "0"))

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GroupDiningMenuBot/0.1)"}
http = httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)

# Places we don't want in a "where should we eat dinner" swipe pool
EXCLUDE_PRIMARY = {
    "bar", "night_club", "cafe", "coffee_shop", "bakery", "ice_cream_shop",
    "dessert_shop", "juice_shop", "tea_house", "candy_store", "wine_bar",
}

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 40_000
MIN_PRICED_ITEMS = 3


# --------------------------------------------------------------------------- db
@contextmanager
def db():
    if not DATABASE_URL:
        raise SystemExit("Set DATABASE_URL in your .env")
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn


def init_db():
    schema = (Path(__file__).parent / "schema.sql").read_text()
    with db() as conn:
        conn.execute(schema)
    print("Schema ready.")


# ------------------------------------------------------------------------- seed
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "nextPageToken",
    "places.id", "places.displayName", "places.formattedAddress", "places.location",
    "places.types", "places.primaryType", "places.websiteUri", "places.rating",
    "places.userRatingCount", "places.priceLevel", "places.priceRange",
])


def _money(m):
    try:
        return float(m["units"]) if m and "units" in m else None
    except (KeyError, ValueError, TypeError):
        return None


def search_neighborhood(name, max_pages=3):
    """Google returns up to 20 per page, 60 max per query."""
    results, token = [], None
    for _ in range(max_pages):
        body = {
            "textQuery": f"restaurants in {name}, New York, NY",
            "includedType": "restaurant",
            "pageSize": 20,
        }
        if token:
            body["pageToken"] = token
        r = http.post(
            PLACES_URL, json=body,
            headers={"X-Goog-Api-Key": GOOGLE_KEY, "X-Goog-FieldMask": FIELD_MASK},
        )
        r.raise_for_status()
        data = r.json()
        results += data.get("places", [])
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(1.5)
    return results


def cuisines_from_types(types):
    return [t.removesuffix("_restaurant") for t in types if t.endswith("_restaurant")]


def seed(neighborhoods):
    if not GOOGLE_KEY:
        raise SystemExit("Set GOOGLE_PLACES_API_KEY in your .env")
    with db() as conn:
        for hood in neighborhoods:
            places = search_neighborhood(hood)
            kept = 0
            for p in places:
                if p.get("primaryType") in EXCLUDE_PRIMARY:
                    continue
                types = p.get("types", [])
                pr = p.get("priceRange") or {}
                site = p.get("websiteUri")
                conn.execute(
                    """
                    INSERT INTO restaurants
                      (place_id, name, address, neighborhood, lat, lng, primary_type, types,
                       cuisines, website, rating, rating_count, google_price_level,
                       google_price_min, google_price_max, menu_status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (place_id) DO UPDATE SET
                      name = EXCLUDED.name, address = EXCLUDED.address,
                      website = EXCLUDED.website, rating = EXCLUDED.rating,
                      rating_count = EXCLUDED.rating_count,
                      google_price_level = EXCLUDED.google_price_level,
                      google_price_min = EXCLUDED.google_price_min,
                      google_price_max = EXCLUDED.google_price_max,
                      updated_at = now()
                    """,
                    (
                        p["id"], p["displayName"]["text"], p.get("formattedAddress"), hood,
                        p.get("location", {}).get("latitude"), p.get("location", {}).get("longitude"),
                        p.get("primaryType"), types, cuisines_from_types(types), site,
                        p.get("rating"), p.get("userRatingCount"), p.get("priceLevel"),
                        _money(pr.get("startPrice")), _money(pr.get("endPrice")),
                        "pending" if site else "no_website",
                    ),
                )
                kept += 1
            conn.commit()
            print(f"{hood}: {len(places)} found, {kept} kept")


# ------------------------------------------------------------- find the menu
SKIP_WORDS = ("gift", "catering", "career", "job", "privacy", "terms")
DEMOTE_WORDS = ("wine", "drink", "cocktail", "dessert", "kid", "beverage", "bar-menu", "happy")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def candidate_links(site_url, name="", hood=""):
    """Menu-looking links on the page, plus (for chain sites) links to this restaurant's own
    location page, e.g. /restaurants/noodle-bar-east-village."""
    r = http.get(site_url)
    base_host = urlparse(str(r.url)).netloc
    soup = BeautifulSoup(r.text, "html.parser")
    hood_slug = slugify(hood)
    name_slug = slugify(name)
    seen, cands = set(), []
    for a in soup.find_all("a", href=True):
        full = urljoin(str(r.url), a["href"])
        hay = (a.get_text(" ", strip=True) + " " + a["href"]).lower()
        hay_slug = slugify(hay)
        if any(w in hay for w in SKIP_WORDS) or full in seen:
            continue
        is_menu = "menu" in hay
        same_site = urlparse(full).netloc == base_host
        is_loc = same_site and ((hood_slug and hood_slug in hay_slug) or (name_slug and name_slug in hay_slug))
        if not (is_menu or is_loc):
            continue
        seen.add(full)
        score = 0 if ".pdf" in full.lower() else 1 if full.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else 2
        if is_menu and is_loc:
            score -= 2
        elif is_loc:
            score += 1
        if any(w in hay for w in DEMOTE_WORDS):
            score += 5
        cands.append((score, full))
    cands.sort(key=lambda x: x[0])
    urls = [u for _, u in cands][:4]
    if str(r.url) not in urls:
        urls.append(str(r.url))  # the page itself is always a last resort
    return urls


def load_source(url):
    """Returns {"kind": pdf|image|text, "data": bytes|str, "mime": str} for the menu at url, or None."""
    r = http.get(url)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").lower().split(";")[0]
    if "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf"):
        if len(r.content) > MAX_PDF_BYTES:
            return None
        return {"kind": "pdf", "data": r.content, "mime": "application/pdf"}
    if ctype in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        return {"kind": "image", "data": r.content, "mime": ctype}
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    if "$" not in text and not any(ch.isdigit() for ch in text):
        return None  # probably a JS-rendered page with no menu in the HTML
    return {"kind": "text", "data": "MENU PAGE TEXT:\n" + text[:MAX_TEXT_CHARS], "mime": "text/plain"}


# ------------------------------------------------------------ parse with an LLM
DIETARY = ["vegetarian", "vegan", "gluten_free", "dairy_free", "nut_free", "halal", "kosher"]

PROMPT = """Extract the FOOD menu from the source provided and return it in the required structure.

Rules:
- Include food only. Skip drinks, wine lists, and cocktails.
- Prices are USD numbers (no $). If an item shows two prices (e.g. 12/15 or small/large), use the lowest.
- category "entree" = a main course meant to be a person's primary dish (pastas, mains, burgers, sandwiches, bowls, pizzas, noodle dishes, etc.). Small plates, starters, and shareables are "appetizer". For cuisines without clear courses (ramen shop, taqueria, pizzeria), mark the main dishes as "entree".
- category "shared" = large-format or family-style dishes meant for 2 or more people (e.g. "serves 2-4", "feeds 4-8", whole chicken or whole fish for the table, platters, tasting spreads). These are NOT entrees; do not count them as one.
- dietary_tags: only when the menu explicitly marks the dish (V, VG, GF, "vegan", etc.) or it is unambiguous. Be conservative; use an empty list if unsure. Use an empty string for a missing description.
- If the restaurant is prix fixe or tasting-menu only, set menu_style accordingly, set prix_fixe_price, and list courses as items only if they have individual prices.
- If the source is not a menu or has no prices, set is_menu=false and items=[]."""

_last_call = 0.0


def _throttle():
    """Free tiers have low requests-per-minute limits; space calls out."""
    global _last_call
    wait = MIN_SECONDS_BETWEEN_CALLS - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


# ---- Gemini (default) ----
DietTag = Literal["vegetarian", "vegan", "gluten_free", "dairy_free", "nut_free", "halal", "kosher"]


class GItem(BaseModel):
    section: str
    category: Literal["appetizer", "entree", "shared", "side", "dessert", "other"]
    name: str
    description: str
    price: float
    dietary_tags: list[DietTag]


class GMenu(BaseModel):
    is_menu: bool
    menu_style: Literal["a_la_carte", "prix_fixe", "tasting", "mixed"]
    prix_fixe_price: Optional[float]
    items: list[GItem]


_gemini = None


def parse_menu_gemini(src):
    global _gemini
    from google import genai
    from google.genai import types

    if _gemini is None:
        _gemini = genai.Client()  # reads GEMINI_API_KEY
    if src["kind"] == "text":
        parts = [src["data"], PROMPT]
    else:
        parts = [types.Part.from_bytes(data=src["data"], mime_type=src["mime"]), PROMPT]

    for attempt in range(3):
        _throttle()
        try:
            resp = _gemini.models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GMenu,
                    max_output_tokens=16000,
                    temperature=0,
                ),
            )
            if resp.parsed is not None:
                return resp.parsed.model_dump()
            return json.loads(resp.text)
        except Exception as e:
            msg = str(e)
            transient = any(k in msg for k in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE"))
            if transient and attempt < 2:
                print("    Gemini busy or rate limited, waiting 30s...")
                time.sleep(30)
                continue
            raise


# ---- Claude (optional: LLM_PROVIDER=claude) ----
MENU_TOOL = {
    "name": "record_menu",
    "description": "Record the food menu extracted from the provided source.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_menu": {"type": "boolean"},
            "menu_style": {"type": "string", "enum": ["a_la_carte", "prix_fixe", "tasting", "mixed"]},
            "prix_fixe_price": {"type": ["number", "null"]},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section": {"type": "string"},
                        "category": {"type": "string", "enum": ["appetizer", "entree", "shared", "side", "dessert", "other"]},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "price": {"type": "number"},
                        "dietary_tags": {"type": "array", "items": {"type": "string", "enum": DIETARY}},
                    },
                    "required": ["section", "category", "name", "price"],
                },
            },
        },
        "required": ["is_menu", "menu_style", "items"],
    },
}
_claude = None


def parse_menu_claude(src):
    global _claude
    import anthropic

    if _claude is None:
        _claude = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    if src["kind"] == "text":
        block = {"type": "text", "text": src["data"]}
    else:
        block = {"type": "document" if src["kind"] == "pdf" else "image",
                 "source": {"type": "base64", "media_type": src["mime"],
                            "data": base64.standard_b64encode(src["data"]).decode()}}
    _throttle()
    resp = _claude.messages.create(
        model=CLAUDE_MODEL, max_tokens=8000, tools=[MENU_TOOL],
        tool_choice={"type": "tool", "name": "record_menu"},
        messages=[{"role": "user", "content": [block, {"type": "text", "text": PROMPT}]}],
    )
    for b in resp.content:
        if b.type == "tool_use":
            return b.input
    return None


def parse_menu(src):
    return parse_menu_claude(src) if PROVIDER == "claude" else parse_menu_gemini(src)


# ------------------------------------------------------------------ run menus
def clean_items(items):
    out = []
    for it in items:
        try:
            price = float(it["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 < price <= 500) or not it.get("name"):
            continue
        it["price"] = round(price, 2)
        out.append(it)
    return out


def process_restaurant(conn, rid, name, website, hood, override):
    last_note = "no candidate menu links worked"
    if override:
        urls = [override]  # you told us exactly where the menu is
    else:
        try:
            urls = candidate_links(website, name, hood)
        except Exception as e:
            return fail(conn, rid, f"could not fetch site: {e}")

    for url in urls:
        try:
            block = load_source(url)
            if block is None:
                last_note = f"no readable menu at {url}"
                continue
            parsed = parse_menu(block)
        except Exception as e:
            last_note = f"{url}: {e}"
            continue
        if not parsed or not parsed.get("is_menu"):
            last_note = f"not a menu: {url}"
            continue
        items = clean_items(parsed.get("items", []))
        priced_prix_fixe = parsed.get("prix_fixe_price")
        if len(items) < MIN_PRICED_ITEMS and not priced_prix_fixe:
            last_note = f"too few priced items at {url}"
            continue
        return save_menu(conn, rid, url, parsed, items)
    return fail(conn, rid, last_note)


def save_menu(conn, rid, url, parsed, items):
    entree_prices = [i["price"] for i in items if i["category"] == "entree"]
    tag_counts = {}
    for i in items:
        for t in i.get("dietary_tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    rest_tags = sorted(t for t, c in tag_counts.items() if c >= 3)

    conn.execute("DELETE FROM menu_items WHERE restaurant_id = %s", (rid,))
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO menu_items (restaurant_id, section, category, name, description, price, dietary_tags)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            [(rid, i.get("section"), i["category"], i["name"], i.get("description"),
              i["price"], i.get("dietary_tags", [])) for i in items],
        )
    conn.execute(
        """UPDATE restaurants SET
             menu_url=%s, menu_style=%s, prix_fixe_price=%s,
             median_entree_price=%s, min_entree_price=%s, max_entree_price=%s,
             entree_count=%s, dietary_tags=%s, menu_status='parsed', menu_note=NULL,
             menu_last_verified=now(), updated_at=now()
           WHERE id=%s""",
        (
            url, parsed.get("menu_style"), parsed.get("prix_fixe_price"),
            statistics.median(entree_prices) if entree_prices else None,
            min(entree_prices) if entree_prices else None,
            max(entree_prices) if entree_prices else None,
            len(entree_prices), rest_tags, rid,
        ),
    )
    return "parsed"


def fail(conn, rid, note):
    conn.execute(
        "UPDATE restaurants SET menu_status='failed', menu_note=%s, updated_at=now() WHERE id=%s",
        (note[:500], rid),
    )
    return "failed"


def run_menus(limit, refresh_days):
    with db() as conn:
        where = "menu_status = 'pending'"
        params = []
        if refresh_days is not None:
            where += (" OR (menu_status = 'parsed' AND menu_last_verified"
                      " < now() - make_interval(days => %s))")
            params.append(refresh_days)
        params.append(limit)
        rows = conn.execute(
            f"""SELECT id, name, website, neighborhood, menu_url_override FROM restaurants
                WHERE (website IS NOT NULL OR menu_url_override IS NOT NULL) AND ({where})
                ORDER BY (menu_url_override IS NOT NULL) DESC, rating_count DESC NULLS LAST
                LIMIT %s""",
            params,
        ).fetchall()
        print(f"Processing {len(rows)} restaurants...")
        counts = {"parsed": 0, "failed": 0}
        for rid, name, website, hood, override in rows:
            status = process_restaurant(conn, rid, name, website, hood, override)
            conn.commit()
            counts[status] += 1
            print(f"  [{status}] {name}")
            time.sleep(1)  # be polite to restaurant sites
        print(counts)


# ------------------------------------------------------------- manual override
def set_menu_url(name_query, url):
    """Point a restaurant at its real menu page and queue it for re-parsing."""
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, neighborhood FROM restaurants WHERE name ILIKE %s",
            (f"%{name_query}%",),
        ).fetchall()
        if len(rows) != 1:
            print(f"{len(rows)} restaurants match '{name_query}':")
            for _, n, h in rows:
                print(f"   {n} ({h})")
            print("Use a more specific name so exactly one matches.")
            return
        conn.execute(
            "UPDATE restaurants SET menu_url_override=%s, menu_status='pending', menu_note=NULL WHERE id=%s",
            (url, rows[0][0]),
        )
        conn.commit()
        print(f"Queued {rows[0][1]} with menu URL {url}")


# ----------------------------------------------------------------------- report
def report():
    with db() as conn:
        print("Status counts:")
        for status, n in conn.execute(
            "SELECT menu_status, count(*) FROM restaurants GROUP BY 1 ORDER BY 2 DESC"
        ):
            print(f"  {status:12} {n}")
        print("\nSample parsed restaurants:")
        for row in conn.execute(
            """SELECT name, neighborhood, median_entree_price, min_entree_price,
                      max_entree_price, entree_count, menu_style
               FROM restaurants WHERE menu_status='parsed'
               ORDER BY random() LIMIT 15"""
        ):
            print("  ", row)
        print("\nRecent failures:")
        for name, note in conn.execute(
            "SELECT name, menu_note FROM restaurants WHERE menu_status='failed' ORDER BY updated_at DESC LIMIT 10"
        ):
            print(f"   {name}: {note}")


# -------------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    s = sub.add_parser("seed")
    s.add_argument("neighborhoods", nargs="+")
    m = sub.add_parser("menus")
    m.add_argument("--limit", type=int, default=25)
    m.add_argument("--refresh-days", type=int, default=None,
                   help="also re-parse menus last verified more than N days ago")
    sub.add_parser("report")
    u = sub.add_parser("menu-url", help="set the exact menu page for one restaurant")
    u.add_argument("name")
    u.add_argument("url")
    args = ap.parse_args()

    if args.cmd == "init-db":
        init_db()
    elif args.cmd == "seed":
        seed(args.neighborhoods)
    elif args.cmd == "menus":
        run_menus(args.limit, args.refresh_days)
    elif args.cmd == "report":
        report()
    elif args.cmd == "menu-url":
        set_menu_url(args.name, args.url)


if __name__ == "__main__":
    main()