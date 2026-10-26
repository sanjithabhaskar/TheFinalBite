-- Privacy + shared deck. Run once:  psql groupdining -f add_privacy_and_deck.sql
--  * members.token : a secret each person's browser holds, so nobody can read or change
--                    someone else's budget/diet just by guessing their id
--  * dining_groups.deck_ids : the one shared deck, frozen when the host starts swiping
ALTER TABLE members ADD COLUMN IF NOT EXISTS token TEXT;
ALTER TABLE dining_groups ADD COLUMN IF NOT EXISTS deck_ids INT[] NOT NULL DEFAULT '{}';

-- Existing members get a token (their old browser sessions won't have it, so create new test groups).
UPDATE members SET token = md5(random()::text || clock_timestamp()::text || id::text) WHERE token IS NULL;

-- Groups that already started: use the restaurants people actually swiped on as the deck.
UPDATE dining_groups g
SET deck_ids = ARRAY(SELECT DISTINCT s.restaurant_id FROM swipes s JOIN members m ON m.id = s.member_id WHERE m.group_id = g.id)
WHERE g.started_at IS NOT NULL AND cardinality(g.deck_ids) = 0;
