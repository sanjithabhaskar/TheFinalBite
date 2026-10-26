-- Example queries for the app. They work on sample data and on real pipeline data.
-- Replace 'SAMPLE1' / ids with real values from your app code (use parameters, never string concatenation).

-- 1. MATCHES: restaurants every member in the group swiped "yes" on
SELECT r.name, r.neighborhood, r.cuisines, r.median_entree_price
FROM group_matches gm
JOIN dining_groups g ON g.id = gm.group_id
JOIN restaurants r   ON r.id = gm.restaurant_id
WHERE g.invite_code = 'SAMPLE1'
ORDER BY r.rating DESC;


-- 2. WHAT TO SHOW A GROUP: fits the LOWEST budget and covers EVERYONE's dietary restrictions.
--    Restaurants with no parsed menu fall back to Google's price range, so they can still appear.
SELECT r.id, r.name, r.neighborhood, r.cuisines,
       COALESCE(r.median_entree_price, r.google_price_max) AS price_guess,
       (r.median_entree_price IS NULL) AS price_is_estimate
FROM restaurants r
WHERE r.menu_style IS DISTINCT FROM 'tasting'                     -- tasting menus need separate handling
  AND r.menu_style IS DISTINCT FROM 'prix_fixe'
  AND COALESCE(r.median_entree_price, r.google_price_max)
        <= (SELECT min(max_entree_budget) FROM members WHERE group_id = (SELECT id FROM dining_groups WHERE invite_code = 'SAMPLE1'))
  AND r.dietary_tags @> (SELECT COALESCE(array_agg(DISTINCT d), ARRAY[]::text[])
                         FROM members m, unnest(m.dietary_restrictions) AS d
                         WHERE m.group_id = (SELECT id FROM dining_groups WHERE invite_code = 'SAMPLE1'))
ORDER BY r.rating DESC;


-- 3. NEXT CARD FOR ONE MEMBER: not swiped yet, fits their budget and diet, preferred cuisines first
SELECT r.id, r.name, r.neighborhood, r.cuisines, r.median_entree_price
FROM members m
JOIN restaurants r ON r.menu_status = 'parsed'
WHERE m.id = (SELECT id FROM members WHERE name = 'Priya' AND group_id = (SELECT id FROM dining_groups WHERE invite_code = 'SAMPLE1'))
  AND r.median_entree_price <= m.max_entree_budget
  AND r.dietary_tags @> m.dietary_restrictions
  AND NOT EXISTS (SELECT 1 FROM swipes s WHERE s.member_id = m.id AND s.restaurant_id = r.id)
ORDER BY (r.cuisines && m.cuisine_prefs) DESC, r.rating DESC
LIMIT 10;


-- 4. RECORD A SWIPE (changing your mind just updates it)
-- INSERT INTO swipes (member_id, restaurant_id, liked)
-- VALUES (:member_id, :restaurant_id, :liked)
-- ON CONFLICT (member_id, restaurant_id) DO UPDATE SET liked = EXCLUDED.liked, created_at = now();


-- 5. SWIPE PROGRESS: who has finished and who hasn't
SELECT m.name, count(s.id) AS swiped, count(*) FILTER (WHERE s.liked) AS liked
FROM members m
LEFT JOIN swipes s ON s.member_id = m.id
WHERE m.group_id = (SELECT id FROM dining_groups WHERE invite_code = 'SAMPLE1')
GROUP BY m.id, m.name
ORDER BY m.name;


-- 6. CREATE A GROUP AND ITS FIRST MEMBER (the invite code is what you put in the share link)
-- WITH g AS (
--   INSERT INTO dining_groups (invite_code, name)
--   VALUES (upper(substr(md5(random()::text), 1, 6)), :group_name)
--   RETURNING id, invite_code)
-- INSERT INTO members (group_id, name, max_entree_budget, dietary_restrictions, cuisine_prefs)
-- SELECT g.id, :name, :budget, :diet, :cuisines FROM g
-- RETURNING (SELECT invite_code FROM g) AS invite_code;


-- 7. ENTREES WITHIN A MEMBER'S BUDGET at one restaurant (nice for the "why this match" screen)
SELECT mi.name, mi.price, mi.dietary_tags
FROM menu_items mi
JOIN restaurants r ON r.id = mi.restaurant_id
WHERE r.name = 'Nonna Rosa''s Trattoria' AND mi.category = 'entree' AND mi.price <= 24
ORDER BY mi.price;


-- 8. HOW MANY OF THE GROUP CAN AFFORD EACH MATCH (for a "fits 3 of 4 budgets" badge)
SELECT r.name, r.median_entree_price,
       count(*) FILTER (WHERE r.median_entree_price <= m.max_entree_budget) AS fits_budget_of,
       count(*) AS group_size
FROM restaurants r
JOIN members m ON m.group_id = (SELECT id FROM dining_groups WHERE invite_code = 'SAMPLE1')
WHERE r.menu_status = 'parsed' AND r.median_entree_price IS NOT NULL
GROUP BY r.id, r.name, r.median_entree_price
HAVING count(*) FILTER (WHERE r.median_entree_price <= m.max_entree_budget) >= 3
ORDER BY fits_budget_of DESC, r.median_entree_price;
