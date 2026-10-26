"""
Restaurant menu pipeline for the group-dining app.

  python pipeline.py init-db
  python pipeline.py seed "East Village" "Williamsburg" "Midtown East"
  python pipeline.py menus --limit 25
  python pipeline.py report
  python pipeline.py menu-url "Noodle Bar" https://example.com/the-menu   (fix a stubborn one by hand)
  python pipeline.py import-csv "Ippudo" ippudo.csv      (type the menu yourself, no AI)
  python pipeline.py set-price "Ippudo" 20 --min 17 --max 24   (quickest: just a typical entree price)

Steps:
  seed   -> Google Places (New) text search per neighborhood -> restaurants table
  menus  -> find menu link on each restaurant's website -> an LLM (Gemini by default) extracts items/prices -> menu_items table
  report -> quick sanity check of what you've collected
"""
import argparse
import base64
import csv
import json
import unicodedata
import os
import re
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

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

# Many restaurant sites block anything that doesn't look like a normal browser, so we look like one.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,image/*;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
}
http = httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)


def clean_url(url):
    """Drop tracking junk like ?utm_source=google (Google's own links carry it and some sites 403 on it)."""
    parts = urlparse(url)
    keep = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "gclid", "fbclid"))]
    return urlunparse(parts._replace(query=urlencode(keep)))


class Page:
    """What fetch() returns: the bits of an HTTP response the rest of the code uses."""
    def __init__(self, url, text, content, headers):
        self.url, self.text, self.content, self.headers = url, text, content, headers


def render(url):
    """Open the page in a real (headless) browser so JavaScript menus and bot checks work.
    Needs:  pip install playwright   and   playwright install chromium"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(user_agent=BROWSER_UA)
            page.goto(url, wait_until="networkidle", timeout=40_000)
            html, final = page.content(), page.url
            browser.close()
        return Page(final, html, html.encode(), {"content-type": "text/html"})
    except Exception:
        return None


def fetch(url, force_render=False):
    """GET a page. Retries when we're told to slow down (429). If the site blocks us (403) or
    we ask for it, falls back to a real browser when Playwright is installed."""
    url = clean_url(url)
    if force_render:
        rendered = render(url)
        if rendered:
            return rendered
    for attempt in range(3):
        r = http.get(url)
        if r.status_code == 429:
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code in (403, 401):
            rendered = render(url)
            if rendered:
                return rendered
        r.raise_for_status()
        return r
    r.raise_for_status()

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
SKIP_WORDS = ("gift", "catering", "career", "job", "privacy", "terms", "login", "cart", "account")
# menus we'd rather not use for "where to eat dinner" (tried only if nothing better works)
DEMOTE_WORDS = ("wine", "drink", "cocktail", "dessert", "kid", "beverage", "bar-menu", "bar menu", "happy",
                "brunch", "breakfast", "lunch", "late night", "late-night")
PREFER_WORDS = ("dinner", "main")
# button/link labels that mean "this is a menu" even without the word menu in them
MENU_LABELS = {"main", "dinner", "dinner menu", "food", "food menu", "view menu", "menu", "menus",
               "dine in", "dine-in", "à la carte", "a la carte"}
# labels that lead to a page about the restaurant itself (a place to look for menu links one level deeper)
HUB_LABELS = {"restaurant", "restaurants", "dining", "dine", "eat", "our restaurants", "food & drink"}


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _scan(page, name, hood):
    """Menu-looking links on one page: [(score, url)], lower score = try first."""
    soup = BeautifulSoup(page.text, "html.parser")
    hood_slug, name_slug = slugify(hood), slugify(name)
    base_host = urlparse(str(page.url)).netloc
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = clean_url(urljoin(str(page.url), href))
        label = a.get_text(" ", strip=True).lower()
        hay = label + " " + href.lower()
        if any(w in hay for w in SKIP_WORDS):
            continue
        hay_slug = slugify(hay)
        same_site = urlparse(full).netloc == base_host
        is_menu = "menu" in hay or label in MENU_LABELS
        is_loc = same_site and ((hood_slug and hood_slug in hay_slug) or (name_slug and name_slug in hay_slug))
        is_hub = same_site and label in HUB_LABELS
        if not (is_menu or is_loc or is_hub):
            continue
        lower = full.lower().split("?")[0]
        score = 0 if lower.endswith(".pdf") else 1 if lower.endswith((".jpg", ".jpeg", ".png", ".webp")) else 2
        if is_menu and is_loc:
            score -= 2
        elif is_loc and not is_menu:
            score += 1
        if is_hub and not is_menu:
            score += 2
        if any(w in hay for w in DEMOTE_WORDS):
            score += 5
        if any(w in hay for w in PREFER_WORDS):
            score -= 1
        found[full] = min(score, found.get(full, 99))
    return sorted((s, u) for u, s in found.items())


def _scan_with_fallback(url, name, hood):
    """Scan a page; if it has no menu-ish links, look again in a real browser (menus often sit in JS popups)."""
    try:
        page = fetch(url)
    except Exception:
        page = None
    links = _scan(page, name, hood) if page else []
    if not links:
        rendered = render(clean_url(url))
        if rendered:
            page, links = rendered, _scan(rendered, name, hood)
    return page, links


def _is_file(url):
    return url.lower().split("?")[0].endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp"))


def candidate_links(site_url, name="", hood=""):
    """Where the menu might be, best guess first. Looks on the homepage, then one level deeper
    (home -> Restaurant page -> Main menu; or Dining -> Gemma -> View menu -> Dinner)."""
    home, level1 = _scan_with_fallback(site_url, name, hood)
    home_url = str(home.url) if home else clean_url(site_url)
    files = [u for _, u in level1 if _is_file(u)]
    pages = [(s, u) for s, u in level1 if not _is_file(u) and u != home_url]

    second = []
    for _, url in pages[:3]:                      # open the best few pages and look for menus inside them
        _, sub = _scan_with_fallback(url, name, hood)
        second += [(s + 1, u) for s, u in sub if u not in (home_url, url)]
    second.sort()

    ordered, seen = [], set()
    for u in files + [u for _, u in second] + [u for _, u in pages] + [home_url]:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered[:8]


def load_local_file(path):
    """A menu you saved yourself: a PDF, or a screenshot (png/jpg/webp)."""
    f = Path(path).expanduser()
    if not f.is_file():
        raise FileNotFoundError(f"no such file: {f}")
    mime = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(f.suffix.lower())
    if mime is None:
        raise ValueError("use a .pdf, .png, .jpg or .webp file")
    data = f.read_bytes()
    return {"kind": "pdf" if mime == "application/pdf" else "image", "data": data, "mime": mime}


PRICE_RE = re.compile(r"(?<![\w:.$/-])\$?\s?\d{1,3}(?:\.\d{2})?(?![\w:/%-])")


def looks_like_menu_text(text):
    """A real menu has lots of prices (with or without a $). Hours, addresses and nav menus don't."""
    return len(PRICE_RE.findall(text)) >= 8


def load_source(url, force_render=False):
    """Returns {"kind": pdf|image|text, "data": bytes|str, "mime": str} for the menu at url, or None."""
    if not url.lower().startswith("http"):
        return load_local_file(url)
    r = fetch(url, force_render)
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
    if not looks_like_menu_text(text):
        if not force_render:
            return load_source(url, force_render=True)   # probably a JavaScript page: try a real browser
        return None
    return {"kind": "text", "data": "MENU PAGE TEXT:\n" + text[:MAX_TEXT_CHARS], "mime": "text/plain"}


# ------------------------------------------------------------ parse with an LLM
DIETARY = ["vegetarian", "vegan", "gluten_free", "dairy_free", "nut_free", "halal", "kosher"]

PROMPT = """Extract the FOOD menu from the source provided and return it in the required structure.

Rules:
- Include food only. Skip drinks, wine lists, and cocktails.
- If the source has separate breakfast, brunch or lunch menus AND a dinner menu, extract ONLY the dinner menu (or the all-day menu). If it only contains breakfast/brunch/lunch items, extract those.
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
    website = clean_url(website) if website else website
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
            url if str(url).lower().startswith("http") else None,
            parsed.get("menu_style"), parsed.get("prix_fixe_price"),
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
            where += (" OR (menu_status = 'parsed' AND menu_note IS DISTINCT FROM 'manual' AND menu_last_verified"
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


# ------------------------------------------------------------------ manual entry
VALID_CATEGORIES = {"appetizer", "entree", "shared", "side", "dessert", "other"}


def _find_one(conn, name_query):
    rows = conn.execute(
        "SELECT id, name, website FROM restaurants WHERE name ILIKE %s", (f"%{name_query}%",)
    ).fetchall()
    if len(rows) != 1:
        print(f"{len(rows)} restaurants match '{name_query}':")
        for _, n, _w in rows:
            print(f"   {n}")
        print("Use a more specific name so exactly one matches.")
        return None
    return rows[0]


def read_menu_csv(path):
    """CSV columns: name, price (required); category, section, description, dietary_tags (optional).
    category defaults to 'entree'. dietary_tags can be separated by ; or ,"""
    items = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            tags = [t.strip().lower() for t in re.split(r"[;,]", row.get("dietary_tags") or "")]
            items.append({
                "section": (row.get("section") or "").strip(),
                "category": ((row.get("category") or "").strip().lower() or "entree"),
                "name": (row.get("name") or "").strip(),
                "description": (row.get("description") or "").strip(),
                "price": (row.get("price") or "").replace("$", "").strip(),
                "dietary_tags": [t for t in tags if t in DIETARY],
            })
    return items


def import_csv(name_query, path):
    """Load a hand-typed menu for one restaurant (no AI involved)."""
    items = read_menu_csv(path)
    bad = sorted({i["category"] for i in items if i["category"] not in VALID_CATEGORIES})
    if bad:
        print(f"Unknown categories {bad}. Use one of: {sorted(VALID_CATEGORIES)}")
        return
    items = clean_items(items)
    if not items:
        print("No valid rows found (each row needs a name and a numeric price).")
        return
    with db() as conn:
        found = _find_one(conn, name_query)
        if not found:
            return
        rid, name, website = found
        save_menu(conn, rid, website, {"menu_style": "a_la_carte", "prix_fixe_price": None}, items)
        conn.execute("UPDATE restaurants SET menu_note='manual' WHERE id=%s", (rid,))
        conn.commit()
        n_entree = sum(1 for i in items if i["category"] == "entree")
        print(f"Saved {len(items)} items for {name} ({n_entree} entrees).")


def set_price(name_query, median, lo, hi):
    """Fastest manual option: just record a typical entree price, no item list."""
    with db() as conn:
        found = _find_one(conn, name_query)
        if not found:
            return
        rid, name, _ = found
        conn.execute(
            """UPDATE restaurants SET median_entree_price=%s, min_entree_price=%s, max_entree_price=%s,
                 menu_style='a_la_carte', menu_status='parsed', menu_note='manual',
                 menu_last_verified=now(), updated_at=now() WHERE id=%s""",
            (median, lo if lo is not None else median, hi if hi is not None else median, rid),
        )
        conn.commit()
        print(f"Saved typical entree price ${median:g} for {name}.")


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
def add_menu(name, url, hood, address, cuisines, rating):
    """Add ONE restaurant from a menu link or a saved file, and parse it now.
    If a restaurant with exactly this name already exists, that one is updated instead of duplicated.
    Returns True if the menu was parsed."""
    is_link = url.lower().startswith("http")
    with db() as conn:
        name = unicodedata.normalize("NFC", name).replace("\u2019", "'").strip()
        same = conn.execute(
            "SELECT id FROM restaurants WHERE lower(replace(name, chr(8217), chr(39))) = lower(%s)", (name,)
        ).fetchall()
        print(("Updating existing" if len(same) == 1 else "NEW restaurant (no exact name match)") + f": {name}")
        if len(same) == 1:
            rid = same[0][0]
            conn.execute(
                """UPDATE restaurants SET menu_url_override=%s, menu_status='pending', menu_note=NULL,
                       neighborhood = COALESCE(%s, neighborhood),
                       cuisines = CASE WHEN cardinality(%s::text[]) > 0 THEN %s::text[] ELSE cuisines END
                   WHERE id=%s""",
                (url, hood, cuisines or [], cuisines or [], rid),
            )
        else:
            place_id = "manual_" + slugify(name) + ("_" + slugify(hood) if hood else "")
            rid = conn.execute(
                """INSERT INTO restaurants (place_id, name, neighborhood, address, website, cuisines, rating,
                                            menu_url_override, menu_status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                   ON CONFLICT (place_id) DO UPDATE
                     SET menu_url_override = EXCLUDED.menu_url_override, menu_status = 'pending', menu_note = NULL
                   RETURNING id""",
                (place_id, name, hood, address, url if is_link else None, cuisines or [], rating, url),
            ).fetchone()[0]
        conn.commit()
        print(f"Parsing {name} from {url} ...")
        process_restaurant(conn, rid, name, None, hood, url)
        conn.commit()
        status, note = conn.execute("SELECT menu_status, menu_note FROM restaurants WHERE id=%s", (rid,)).fetchone()
        if status == "parsed":
            m = conn.execute(
                "SELECT median_entree_price, entree_count FROM restaurants WHERE id=%s", (rid,)
            ).fetchone()
            print(f"  [ok] {name}: median entree ${m[0]} from {m[1]} entrees")
            return True
        print(f"  [failed] {name}: {note}")
        return False


def add_folder(folder, hood, cuisines, limit=None):
    """Parse every menu file in a folder. The file name IS the restaurant name:
         Cafe Mogador.pdf, Smor.png, Little_Kirin.jpg   (underscores become spaces)
       Files that parse are moved into a 'done' subfolder, so you can re-run safely."""
    d = Path(folder).expanduser()
    if not d.is_dir():
        print(f"No such folder: {d}")
        return
    files = sorted(f for f in d.iterdir() if f.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".webp"))
    if limit:
        files = files[:limit]
    print(f"{len(files)} menu files in {d}")
    done = d / "done"
    ok = 0
    for f in files:
        name = " ".join(f.stem.replace("_", " ").split())
        try:
            if add_menu(name, str(f), hood, None, cuisines, None):
                done.mkdir(exist_ok=True)
                f.rename(done / f.name)
                ok += 1
        except Exception as e:
            print(f"  [error] {name}: {e}")
    print(f"Parsed {ok} of {len(files)}.")


def add_list(path, default_hood):
    """Add many restaurants from a plain text file. One per line:
         Name | menu link or file | neighborhood (optional) | cuisines, comma separated (optional)
       Blank lines and lines starting with # are ignored."""
    lines = [l.strip() for l in Path(path).expanduser().read_text().splitlines()]
    todo = [l for l in lines if l and not l.startswith("#")]
    print(f"{len(todo)} restaurants to add")
    for line in todo:
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 2 or not parts[1]:
            print(f"  skipped (needs 'name | link'): {line}")
            continue
        hood = parts[2] if len(parts) > 2 and parts[2] else default_hood
        cuisines = [c.strip() for c in parts[3].split(",") if c.strip()] if len(parts) > 3 else []
        try:
            add_menu(parts[0], parts[1], hood, None, cuisines, None)
        except Exception as e:
            print(f"  [error] {parts[0]}: {e}")


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
    c = sub.add_parser("import-csv", help="load a hand-typed menu for one restaurant")
    c.add_argument("name")
    c.add_argument("file")
    a = sub.add_parser("add-menu", help="add a restaurant from its menu page URL and parse it now")
    a.add_argument("name")
    a.add_argument("url")
    a.add_argument("--hood", default=None, help="neighborhood, e.g. 'East Village'")
    a.add_argument("--address", default=None)
    a.add_argument("--cuisine", action="append", default=[], help="repeat for several, e.g. --cuisine thai")
    a.add_argument("--rating", type=float, default=None)
    fo = sub.add_parser("add-folder", help="parse every menu PDF/screenshot in a folder (file name = restaurant name)")
    fo.add_argument("folder")
    fo.add_argument("--hood", default=None, help="neighborhood for all of them, e.g. 'East Village'")
    fo.add_argument("--limit", type=int, default=None, help="only do the first N files this run")
    fo.add_argument("--cuisine", action="append", default=[], help="cuisine for all of them (rarely useful)")
    l = sub.add_parser("add-list", help="add many restaurants from a text file of 'name | menu link or file'")
    l.add_argument("file")
    l.add_argument("--hood", default=None, help="default neighborhood for lines that don't give one")
    p = sub.add_parser("set-price", help="just record a typical entree price for one restaurant")
    p.add_argument("name")
    p.add_argument("median", type=float)
    p.add_argument("--min", type=float, dest="lo")
    p.add_argument("--max", type=float, dest="hi")
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
    elif args.cmd == "import-csv":
        import_csv(args.name, args.file)
    elif args.cmd == "add-menu":
        add_menu(args.name, args.url, args.hood, args.address, args.cuisine, args.rating)
    elif args.cmd == "add-folder":
        add_folder(args.folder, args.hood, args.cuisine, args.limit)
    elif args.cmd == "add-list":
        add_list(args.file, args.hood)
    elif args.cmd == "set-price":
        set_price(args.name, args.median, args.lo, args.hi)


if __name__ == "__main__":
    main()