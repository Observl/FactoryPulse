CREATE TABLE IF NOT EXISTS auth_users(user_id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE,display_name TEXT NOT NULL,role TEXT NOT NULL,staff_id TEXT,password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_attempts(attempt_key TEXT PRIMARY KEY,attempts INTEGER NOT NULL,window_start TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_onboarding(user_id TEXT PRIMARY KEY REFERENCES auth_users(user_id) ON DELETE CASCADE,step INTEGER NOT NULL DEFAULT 0,completed_at TEXT);
CREATE TABLE IF NOT EXISTS audit_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,entity_id TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fp_identity_revision(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,commit_nonce TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fp_identity_guard(id INTEGER PRIMARY KEY CONSTRAINT fp_identity_guard_revision CHECK(id=1));
INSERT OR IGNORE INTO fp_identity_revision VALUES(1,0,'initial');
CREATE INDEX IF NOT EXISTS auth_sessions_expiry ON auth_sessions(expires_at);
