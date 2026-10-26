# Menu pipeline

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
