-- Guestbook storage. See specs/2026-08-20-guestbook-design.md section 5.
--
-- `message` holds RAW text exactly as typed. The profanity swap is a
-- render-time transform, never a write-time one, so the policy stays
-- reversible and nothing the visitor wrote is ever lost.
--
-- `ip_hash` is sha256(RATE_SALT || ip) truncated to 32 hex chars. Rate
-- limiting works without the site ever holding a visitor's address.
--
-- `hidden` is a soft delete. Blocked entries are stored hidden rather
-- than destroyed so filter misfires are auditable instead of invisible.

CREATE TABLE IF NOT EXISTS entries (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT    NOT NULL,
  message      TEXT    NOT NULL,
  created_at   TEXT    NOT NULL,
  ip_hash      TEXT    NOT NULL,
  hidden       INTEGER NOT NULL DEFAULT 0,
  block_reason TEXT
);

-- Serves the public read: WHERE hidden = 0 ORDER BY id DESC LIMIT ?
CREATE INDEX IF NOT EXISTS idx_entries_visible
  ON entries (hidden, id DESC);

-- Serves the rate-limit count: WHERE ip_hash = ? AND created_at > ?
CREATE INDEX IF NOT EXISTS idx_entries_ip
  ON entries (ip_hash, created_at);
