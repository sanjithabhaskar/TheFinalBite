-- App tables. Run AFTER schema.sql (these reference the restaurants table).
--   psql groupdining -f schema.sql
--   psql groupdining -f app_schema.sql

CREATE TABLE IF NOT EXISTS dining_groups (
    id            SERIAL PRIMARY KEY,
    invite_code   TEXT UNIQUE NOT NULL,             -- what people type or the link carries
    name          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS members (
    id                    SERIAL PRIMARY KEY,
    group_id              INT NOT NULL REFERENCES dining_groups(id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    max_entree_budget     NUMERIC(6,2) NOT NULL,     -- most they'd pay for one entree, before tax/tip
    dietary_restrictions  TEXT[] NOT NULL DEFAULT '{}',  -- vegetarian, vegan, gluten_free, dairy_free, nut_free, halal, kosher
    cuisine_prefs         TEXT[] NOT NULL DEFAULT '{}',  -- same vocabulary as restaurants.cuisines
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS swipes (
    id             SERIAL PRIMARY KEY,
    member_id      INT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    restaurant_id  INT NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    liked          BOOLEAN NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (member_id, restaurant_id)
);

CREATE INDEX IF NOT EXISTS idx_members_group ON members(group_id);
CREATE INDEX IF NOT EXISTS idx_swipes_member ON swipes(member_id);
CREATE INDEX IF NOT EXISTS idx_swipes_restaurant ON swipes(restaurant_id);

-- A match = every member currently in the group swiped "yes" on the restaurant.
CREATE OR REPLACE VIEW group_matches AS
SELECT m.group_id, s.restaurant_id, count(*) AS yes_votes
FROM swipes s
JOIN members m ON m.id = s.member_id
WHERE s.liked
GROUP BY m.group_id, s.restaurant_id
HAVING count(*) = (SELECT count(*) FROM members m2 WHERE m2.group_id = m.group_id);
