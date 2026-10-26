-- Adds "who is the host" and "has swiping started" to groups.
-- Run once:  psql groupdining -f add_host_and_start.sql
ALTER TABLE dining_groups ADD COLUMN IF NOT EXISTS host_member_id INT REFERENCES members(id) ON DELETE SET NULL;
ALTER TABLE dining_groups ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

-- Existing groups: the earliest member becomes the host.
UPDATE dining_groups g
SET host_member_id = (SELECT min(m.id) FROM members m WHERE m.group_id = g.id)
WHERE host_member_id IS NULL;

-- The two sample groups already have swipes, so treat them as started.
UPDATE dining_groups SET started_at = now() WHERE invite_code IN ('SAMPLE1', 'SAMPLE2') AND started_at IS NULL;
