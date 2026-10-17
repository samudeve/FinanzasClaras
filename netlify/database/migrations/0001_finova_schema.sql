CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL,
  username_key TEXT NOT NULL UNIQUE,
  password_salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS movements (
  id TEXT NOT NULL,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('income', 'expense')),
  category TEXT NOT NULL,
  title TEXT NOT NULL,
  amount NUMERIC(14,2) NOT NULL CHECK (amount > 0),
  occurred_at TEXT NOT NULL,
  PRIMARY KEY (user_id, id)
);

CREATE INDEX IF NOT EXISTS movements_user_date ON movements(user_id, occurred_at);

CREATE TABLE IF NOT EXISTS loans (
  id TEXT NOT NULL,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  entity TEXT NOT NULL DEFAULT '',
  principal NUMERIC(14,2) NOT NULL CHECK (principal > 0),
  paid NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (paid >= 0 AND paid <= principal),
  interest NUMERIC(8,3) NOT NULL DEFAULT 0 CHECK (interest >= 0),
  interest_type TEXT NOT NULL DEFAULT 'annual' CHECK (interest_type IN ('annual','monthly')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, id)
);

CREATE TABLE IF NOT EXISTS goals (
  id TEXT NOT NULL,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  target NUMERIC(14,2) NOT NULL CHECK (target > 0),
  saved NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (saved >= 0),
  due TEXT NOT NULL DEFAULT '',
  emoji TEXT NOT NULL DEFAULT '✳',
  PRIMARY KEY (user_id, id)
);

CREATE TABLE IF NOT EXISTS events (
  id TEXT NOT NULL,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('loan','goal')),
  title TEXT NOT NULL,
  amount NUMERIC(14,2) NOT NULL CHECK (amount > 0),
  occurred_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (user_id, id)
);

CREATE INDEX IF NOT EXISTS events_user_date ON events(user_id, occurred_at);
