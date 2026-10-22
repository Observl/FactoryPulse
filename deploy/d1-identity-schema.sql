CREATE TABLE IF NOT EXISTS auth_users(user_id INTEGER PRIMARY KEY AUTOINCREMENT CHECK(user_id>=10001),display_name TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('开发者','管理员','普通用户','只读用户')),staff_id INTEGER NOT NULL,password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),CHECK((role='开发者' AND staff_id=0) OR (role='管理员' AND staff_id=-1) OR (role IN ('普通用户','只读用户') AND staff_id>0)));
INSERT INTO sqlite_sequence(name,seq) SELECT 'auth_users',10000 WHERE NOT EXISTS(SELECT 1 FROM sqlite_sequence WHERE name='auth_users');
CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_attempts(attempt_key TEXT PRIMARY KEY,attempts INTEGER NOT NULL,window_start TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_onboarding(user_id TEXT PRIMARY KEY REFERENCES auth_users(user_id) ON DELETE CASCADE,step INTEGER NOT NULL DEFAULT 0,completed_at TEXT);
CREATE TABLE IF NOT EXISTS audit_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,entity_id TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fp_identity_revision(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,commit_nonce TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fp_identity_guard(id INTEGER PRIMARY KEY CONSTRAINT fp_identity_guard_revision CHECK(id=1));
INSERT OR IGNORE INTO fp_identity_revision VALUES(1,0,'initial');
CREATE INDEX IF NOT EXISTS auth_sessions_expiry ON auth_sessions(expires_at);

CREATE TABLE IF NOT EXISTS auth_id_sequence(id INTEGER PRIMARY KEY CHECK(id=1),next_id INTEGER NOT NULL CHECK(next_id>=10001));
INSERT OR IGNORE INTO auth_id_sequence VALUES(1,10001);
