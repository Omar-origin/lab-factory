ALTER TABLE orders ADD COLUMN promotion_code TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN promotion_discount_cents INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS promotion_reservations (
  user_id TEXT NOT NULL REFERENCES users(id),
  promotion_code TEXT NOT NULL,
  source_order_id TEXT NOT NULL REFERENCES orders(id),
  reserved_order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
  discount_cents INTEGER NOT NULL CHECK(discount_cents > 0),
  state TEXT NOT NULL DEFAULT 'reserved' CHECK(state IN ('reserved','redeemed')),
  created_at TEXT NOT NULL,
  redeemed_at TEXT,
  PRIMARY KEY(user_id,promotion_code)
);

CREATE INDEX IF NOT EXISTS promotion_reservations_state
  ON promotion_reservations(state, created_at DESC);
