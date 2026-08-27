ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user';
ALTER TABLE users ADD COLUMN role_updated_at TEXT;

ALTER TABLE orders ADD COLUMN expires_at TEXT;
ALTER TABLE orders ADD COLUMN cancelled_at TEXT;
ALTER TABLE orders ADD COLUMN user_hidden_at TEXT;

CREATE TABLE IF NOT EXISTS admin_invites (
  id TEXT PRIMARY KEY,
  code_hash TEXT NOT NULL UNIQUE,
  code_suffix TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('owner','distributor_admin')),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','revoked','exhausted')),
  max_uses INTEGER NOT NULL DEFAULT 1 CHECK(max_uses BETWEEN 1 AND 100),
  use_count INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT NOT NULL,
  created_by_user_id TEXT REFERENCES users(id),
  created_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS admin_invites_status_expires ON admin_invites(status, expires_at DESC);

CREATE TABLE IF NOT EXISTS admin_invite_redemptions (
  invite_id TEXT NOT NULL REFERENCES admin_invites(id),
  user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
  redeemed_at TEXT NOT NULL,
  PRIMARY KEY(invite_id,user_id)
);

CREATE TABLE IF NOT EXISTS admin_audit_events (
  id TEXT PRIMARY KEY,
  actor_user_id TEXT REFERENCES users(id),
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS admin_audit_created ON admin_audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS admin_audit_target ON admin_audit_events(target_type,target_id,created_at DESC);

CREATE TABLE IF NOT EXISTS visitor_days (
  metric_date TEXT NOT NULL,
  route TEXT NOT NULL,
  visitor_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(metric_date,route,visitor_hash)
);

CREATE TABLE IF NOT EXISTS daily_site_metrics (
  metric_date TEXT NOT NULL,
  route TEXT NOT NULL,
  page_views INTEGER NOT NULL DEFAULT 0,
  unique_visitors INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(metric_date,route)
);

CREATE INDEX IF NOT EXISTS orders_user_visible_created ON orders(user_id,user_hidden_at,created_at DESC);
