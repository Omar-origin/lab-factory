ALTER TABLE license_keys ADD COLUMN plan TEXT NOT NULL DEFAULT 'permanent';
ALTER TABLE license_keys ADD COLUMN usage_limit INTEGER;
ALTER TABLE orders ADD COLUMN plan TEXT NOT NULL DEFAULT 'experience';

CREATE TABLE IF NOT EXISTS usage_events (
  id TEXT PRIMARY KEY,
  license_key_id TEXT NOT NULL REFERENCES license_keys(id),
  usage_id TEXT NOT NULL,
  used_at TEXT NOT NULL,
  UNIQUE(license_key_id, usage_id)
);
CREATE INDEX IF NOT EXISTS usage_key_used ON usage_events(license_key_id, used_at DESC);
