-- UI redesign plan C (spec §8): the report's one opening sentence, kept with the report so lists and mails show it.
-- Reports made before this have none ('').
ALTER TABLE reports ADD COLUMN conclusion TEXT NOT NULL DEFAULT '';
