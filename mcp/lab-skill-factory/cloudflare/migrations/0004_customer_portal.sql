PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
  invited_by_user_id TEXT REFERENCES users(id),
  store_credit_cents INTEGER NOT NULL DEFAULT 0,
  verified_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS users_inviter_created ON users(invited_by_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS email_challenges (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT 'login',
  code_hash TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT NOT NULL,
  consumed_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS email_challenges_email_created ON email_challenges(email, created_at DESC);

CREATE TABLE IF NOT EXISTS user_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS user_sessions_user_expires ON user_sessions(user_id, expires_at DESC);

CREATE TABLE IF NOT EXISTS referral_codes (
  code TEXT PRIMARY KEY,
  user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS referral_attributions (
  invited_user_id TEXT PRIMARY KEY REFERENCES users(id),
  referrer_user_id TEXT NOT NULL REFERENCES users(id),
  code TEXT NOT NULL REFERENCES referral_codes(code),
  created_at TEXT NOT NULL,
  CHECK(invited_user_id != referrer_user_id)
);
CREATE INDEX IF NOT EXISTS referral_attributions_referrer ON referral_attributions(referrer_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS entitlements (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id),
  order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
  plan TEXT NOT NULL CHECK(plan IN ('experience','permanent','team')),
  major_version INTEGER,
  seat_count INTEGER NOT NULL CHECK(seat_count BETWEEN 1 AND 5),
  free_major_updates INTEGER NOT NULL DEFAULT 0 CHECK(free_major_updates IN (0,1)),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entitlements_user_created ON entitlements(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS commission_entries (
  id TEXT PRIMARY KEY,
  referrer_user_id TEXT NOT NULL REFERENCES users(id),
  invited_user_id TEXT NOT NULL REFERENCES users(id),
  order_id TEXT NOT NULL REFERENCES orders(id),
  basis_cents INTEGER NOT NULL,
  rate_bps INTEGER NOT NULL DEFAULT 2000,
  amount_cents INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','withdrawal_pending','withdrawn','converted','reversed')),
  available_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(order_id, referrer_user_id)
);
CREATE INDEX IF NOT EXISTS commission_referrer_status ON commission_entries(referrer_user_id, status, available_at DESC);

CREATE TABLE IF NOT EXISTS withdrawal_requests (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  payout_note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','paid','rejected')),
  created_at TEXT NOT NULL,
  processed_at TEXT,
  admin_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS withdrawals_status_created ON withdrawal_requests(status, created_at DESC);

CREATE TABLE IF NOT EXISTS notices (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'info' CHECK(level IN ('info','success','warning')),
  published_at TEXT NOT NULL,
  expires_at TEXT
);

INSERT OR IGNORE INTO notices(id,title,body,level,published_at) VALUES
  ('welcome-v1','Lab Factory 用户中心开始搭建','套餐、设备、订单和邀请返佣将统一在账号中管理。','info','2026-08-25T00:00:00+00:00'),
  ('support-v1','售后支持','遇到激活、付款或密钥问题，请加入售后 QQ 群 923937311。','success','2026-08-25T00:00:00+00:00');

ALTER TABLE orders ADD COLUMN user_id TEXT REFERENCES users(id);
ALTER TABLE orders ADD COLUMN gross_amount_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN credit_applied_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN major_version INTEGER;
ALTER TABLE license_keys ADD COLUMN entitlement_id TEXT REFERENCES entitlements(id);
ALTER TABLE license_keys ADD COLUMN order_id TEXT REFERENCES orders(id);
ALTER TABLE license_keys ADD COLUMN seat_index INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS orders_user_created ON orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS license_keys_order_seat ON license_keys(order_id, seat_index);
