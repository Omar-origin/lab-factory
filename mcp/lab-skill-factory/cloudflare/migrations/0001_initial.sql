PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS license_keys (
  id TEXT PRIMARY KEY,
  key_hash TEXT NOT NULL UNIQUE,
  key_suffix TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('unused','active','refund_requested','refunded','banned')),
  label TEXT NOT NULL DEFAULT '',
  customer_ref TEXT NOT NULL DEFAULT '',
  refund_days INTEGER NOT NULL CHECK(refund_days IN (3,7)),
  product_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  sent_at TEXT,
  activated_at TEXT,
  refund_deadline TEXT,
  install_id TEXT,
  device_public_key TEXT,
  activation_token_hash TEXT,
  last_seen_at TEXT,
  revoked_at TEXT,
  revoke_reason TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_activation_token ON license_keys(activation_token_hash) WHERE activation_token_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS unique_order_license ON license_keys(customer_ref) WHERE customer_ref LIKE 'lforder_%';
CREATE INDEX IF NOT EXISTS license_keys_status_created ON license_keys(status, created_at DESC);

CREATE TABLE IF NOT EXISTS request_nonces (
  nonce TEXT PRIMARY KEY,
  license_key_id TEXT NOT NULL REFERENCES license_keys(id),
  used_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY,
  license_key_id TEXT REFERENCES license_keys(id),
  event TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_key_created ON audit_events(license_key_id, created_at DESC);

CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY,
  status_token_hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN ('payment_pending','payment_submitted','payment_rejected','paid','key_issued','delivered','refund_requested','refunded')),
  product_id TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  currency TEXT NOT NULL,
  payment_provider TEXT NOT NULL,
  contact TEXT NOT NULL DEFAULT '',
  payment_reference TEXT NOT NULL DEFAULT '',
  payment_claimed_at TEXT,
  refund_days INTEGER NOT NULL CHECK(refund_days IN (3,7)),
  license_key_id TEXT REFERENCES license_keys(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  paid_at TEXT,
  delivered_at TEXT,
  refund_requested_at TEXT,
  refunded_at TEXT,
  admin_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS orders_status_created ON orders(status, created_at DESC);

CREATE TABLE IF NOT EXISTS order_audit_events (
  id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL REFERENCES orders(id),
  event TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS order_audit_created ON order_audit_events(order_id, created_at DESC);
