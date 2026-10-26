CREATE TABLE IF NOT EXISTS restaurants (
    id                   SERIAL PRIMARY KEY,
    place_id             TEXT UNIQUE NOT NULL,          -- Google Places ID
    name                 TEXT NOT NULL,
    address              TEXT,
    neighborhood         TEXT,
    lat                  DOUBLE PRECISION,
    lng                  DOUBLE PRECISION,
    primary_type         TEXT,
    types                TEXT[] DEFAULT '{}',
    cuisines             TEXT[] DEFAULT '{}',
    website              TEXT,
    rating               NUMERIC(2,1),
    rating_count         INT,

    -- Google's own price info (fallback when no menu could be parsed)
    google_price_level   TEXT,
    google_price_min     NUMERIC,
    google_price_max     NUMERIC,

    -- Parsed from the real menu
    menu_url             TEXT,
    menu_style           TEXT,                          -- a_la_carte | prix_fixe | tasting | mixed
    prix_fixe_price      NUMERIC,                       -- per person, if prix fixe / tasting
    median_entree_price  NUMERIC,
    min_entree_price     NUMERIC,
    max_entree_price     NUMERIC,
    entree_count         INT DEFAULT 0,
    dietary_tags         TEXT[] DEFAULT '{}',           -- restaurant-level (>= 3 items carry the tag)

    menu_status          TEXT NOT NULL DEFAULT 'pending', -- pending | parsed | failed | no_website
    menu_note            TEXT,
    menu_last_verified   TIMESTAMPTZ,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS menu_items (
    id             SERIAL PRIMARY KEY,
    restaurant_id  INT NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    section        TEXT,                                -- as printed on the menu ("Pastas")
    category       TEXT NOT NULL,                       -- appetizer | entree | side | dessert | other
    name           TEXT NOT NULL,
    description    TEXT,
    price          NUMERIC(8,2) NOT NULL,
    dietary_tags   TEXT[] DEFAULT '{}'                  -- vegetarian, vegan, gluten_free, dairy_free, nut_free, halal, kosher
);

CREATE INDEX IF NOT EXISTS idx_menu_items_restaurant ON menu_items(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_restaurants_median ON restaurants(median_entree_price);
CREATE INDEX IF NOT EXISTS idx_restaurants_cuisines ON restaurants USING GIN (cuisines);
CREATE INDEX IF NOT EXISTS idx_restaurants_dietary ON restaurants USING GIN (dietary_tags);

-- added later: lets you point a restaurant at its exact menu page
ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS menu_url_override TEXT;