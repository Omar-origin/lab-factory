ALTER TABLE commission_entries ADD COLUMN withdrawal_id TEXT REFERENCES withdrawal_requests(id);
CREATE INDEX IF NOT EXISTS commission_withdrawal ON commission_entries(withdrawal_id);
