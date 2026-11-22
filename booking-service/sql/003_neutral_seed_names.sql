-- Removes the word "Demo" from the seeded names. Safe to run repeatedly: it only
-- touches rows that still have the original seed text, so edited rows are kept.
UPDATE users    SET name = 'Customer A' WHERE name = 'Demo User A';
UPDATE users    SET name = 'Customer B' WHERE name = 'Demo User B';
UPDATE concerts SET concert_name = 'Concert A', description = 'Live concert at Sample Arena'
 WHERE concert_name = 'Demo Concert A';
UPDATE concerts SET concert_name = 'Concert B', description = 'Live concert at Sample Hall'
 WHERE concert_name = 'Demo Concert B';
