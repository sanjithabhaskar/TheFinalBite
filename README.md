# The Final Bite

**Dinner, decided together.** A group restaurant-matching app: everyone in a group enters a budget and
(optionally) dietary needs and cuisines, swipes the same deck of restaurants, and the places everyone
said yes to become your matches.

### Try it live: https://the-final-bite.vercel.app/


> The API runs on a free Render instance that sleeps after ~15 minutes idle, so the very first
> request after a quiet spell can take around 30 seconds. After that it's fast.

---

## How it works

1. **Make a group.** The host enters their name, a group name, a max budget per entrée, and optional
   dietary restrictions and cuisines. They get a 6-character invite code / link.
2. **Gather your group.** Friends join with the code and add their own budget and preferences.
3. **Swipe & agree.** The host starts the group, everyone swipes through one shared deck of restaurants
   that fits the whole group (budget, dietary needs). A restaurant becomes a **match** only when every
   member says yes.

### Privacy by design
Members never see each other's budget, dietary restrictions or cuisine choices. The UI and the API only
ever show generic wording like "Fits everyone's budget"; a person sees only their own preferences.

## Tech stack

| Layer | What | Where it runs |
|---|---|---|
| Frontend | Angular (standalone components, signals), TypeScript | Vercel |
| API | Django + Django REST-style JSON endpoints, gunicorn, whitenoise | Render |
| Database | PostgreSQL | Neon |
| Data | Python pipeline: Google Places (New) → menu scraping → LLM parsing → Postgres | run locally |

Seed data is 86 East Village (NYC) restaurants with parsed menus and prices.

## Repo layout

```
frontend/   Angular app (src/app/<screen>/, shared header/footer, services/restaurant-api.ts)
backend/    Django project (backend/backend/settings.py) and the `api` app
pipeline/   Menu pipeline + SQL schema/sample data (documented below)
```

## API

Base URL: `https://thefinalbite.onrender.com/api`

| Method | Path | Purpose |
|---|---|---|
| GET | `restaurants/` | List restaurants |
| POST | `groups/` | Create a group (host) |
| GET | `groups/<invite_code>/` | Look up a group by invite code |
| POST | `groups/<invite_code>/join/` | Join a group as a member |
| POST | `groups/<invite_code>/start/` | Host starts the swiping |
| GET | `groups/<invite_code>/matches/` | Restaurants everyone said yes to |
| GET/PATCH | `members/<id>/` | A member's own details |
| GET | `members/<id>/next/` | Next card in that member's deck |
| POST | `swipes/` | Record a yes/no swipe |

Members authenticate each request with an `X-Member-Token` header.

## Run it locally

**API**
```
cd backend
pip install -r requirements.txt
# needs a local Postgres; default DATABASE_URL is postgresql://<you>@localhost:5432/groupdining
python manage.py runserver
```

**Frontend**
```
cd frontend
npm install
npm start          # http://localhost:4200
```
Set the API base URL in `frontend/src/app/services/restaurant-api.ts`
(`http://localhost:8000/api` for local, the Render URL for production).

## Deploying

- **Database (Neon):** import the schema with `psql` using the **direct** connection string
  (no `-pooler`); use the **pooled** string for the running API.
- **API (Render):** Root Directory `backend`, Build `pip install -r requirements.txt`,
  Start `gunicorn backend.wsgi`. Environment variables:
  `SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS` (host only, no `https://`),
  `CORS_ORIGINS` (your full Vercel URL, no trailing slash).
- **Frontend (Vercel):** Root Directory `frontend`, Angular preset, Output Directory
  `dist/frontend/browser`. `frontend/vercel.json` rewrites all routes to `/index.html`.
  Pushing to GitHub redeploys automatically.

> Never commit secrets. Keep connection strings and keys in environment variables / `.env`
> (which is git-ignored). If a secret is ever pasted somewhere public, rotate it.

---

# Data pipeline (menu pipeline)

## Setup
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in the keys
   (Google Cloud project with "Places API (New)" enabled; Gemini key from aistudio.google.com/apikey; Postgres URL).
   To use Claude instead of Gemini, set `LLM_PROVIDER=claude` and add `ANTHROPIC_API_KEY`.
3. `python pipeline.py init-db`

## Run
```
python pipeline.py seed "East Village" "Williamsburg" "Midtown East"
python pipeline.py menus --limit 25      # start small, then check the report
python pipeline.py report
python pipeline.py menus --limit 500     # once the sample looks right
python pipeline.py menus --refresh-days 60   # monthly refresh of old menus
```

## Spot-check
Open `restaurants.menu_url` for ~20 parsed rows and compare against `menu_items`.
If prices or categories look off, tweak `PROMPT` in pipeline.py and re-run
(set menu_status back to 'pending' for rows you want re-parsed).

## Example app queries
```sql
-- Restaurants where a group's lowest budget ($25) fits and everyone's dietary needs are covered
SELECT name, neighborhood, median_entree_price
FROM restaurants
WHERE menu_status = 'parsed'
  AND median_entree_price <= 25
  AND dietary_tags @> ARRAY['vegetarian','gluten_free']
  AND cuisines && ARRAY['italian','thai'];

-- Specific dishes within budget at one restaurant
SELECT name, price FROM menu_items
WHERE restaurant_id = 123 AND category = 'entree' AND price <= 25;
```

## Notes
- Google's terms limit how long you can cache Places data; check current terms. Storing place_id and refetching is the safe pattern.
- Only fetches public restaurant websites; sleeps between requests.
- Sites that render menus with JavaScript only (or embed them in Instagram) will land in `failed`; handle those manually or via a later Playwright step.

## Fixing a stubborn restaurant by hand
Chain sites (e.g. Momofuku) list several locations, so Google's website link may not be the page with the menu.
Find the real menu page in your browser, then:
```
python3 pipeline.py init-db        # one time, adds the override column
python3 pipeline.py menu-url "Momofuku Noodle Bar" https://www.momofuku.com/restaurants/noodle-bar-east-village
python3 pipeline.py menus --limit 1
```

## Filling in menus by hand (no AI)
Best for restaurants that always fail (menus inside Instagram posts, QR ordering apps, etc.).
- **Quickest** (just a typical entree price): `python3 pipeline.py set-price "Ippudo" 20 --min 17 --max 24`
- **Full menu:** copy `menu_template.csv`, replace the rows with the real menu (`name` and `price` are required;
  `category` defaults to entree), then `python3 pipeline.py import-csv "Ippudo" ippudo.csv`
Manual entries are marked `menu_note = 'manual'` and are never overwritten by `--refresh-days`.
To list good candidates: `psql groupdining -c "SELECT name, website FROM restaurants WHERE menu_status='failed';"`

## App tables and sample data (for building the app before the real data is ready)
```
psql groupdining -f app_schema.sql     # dining_groups, members, swipes, group_matches view
psql groupdining -f sample_data.sql    # 26 fictional restaurants, 190 menu items, 3 groups, 120 swipes
psql groupdining -f sample_queries.sql # example queries: matches, what to show a group, next card, swipe upsert...
```
- Sample restaurants have `place_id` starting with `sample_`; sample groups have invite codes `SAMPLE1`..`SAMPLE3`.
- Everything is fictional (names, addresses, prices). Real pipeline rows are never touched.
- `sample_data.sql` is safe to re-run. To remove it:
  `DELETE FROM dining_groups WHERE invite_code LIKE 'SAMPLE%'; DELETE FROM restaurants WHERE place_id LIKE 'sample\_%';`
- To exclude sample rows from real queries: `WHERE place_id NOT LIKE 'sample\_%'`
