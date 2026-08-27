ALTER TABLE users ADD COLUMN password_hash TEXT;
ALTER TABLE users ADD COLUMN password_salt TEXT;
ALTER TABLE users ADD COLUMN password_iterations INTEGER;
ALTER TABLE users ADD COLUMN password_set_at TEXT;
ALTER TABLE users ADD COLUMN failed_login_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN login_locked_until TEXT;

CREATE INDEX IF NOT EXISTS users_login_lock ON users(email, login_locked_until);
