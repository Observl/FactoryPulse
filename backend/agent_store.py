"""SQLite session isolation, bounded memory, run traces and single-use permissions."""
import hashlib
import json
import time
import uuid
from fastapi import HTTPException


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class AgentStore:
    def __init__(self, connect):
        self.connect = connect
        with connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS agent_sessions (id TEXT PRIMARY KEY, owner TEXT NOT NULL, content TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS agent_runs (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, content TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS agent_permissions (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, content TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS agent_memory (id TEXT PRIMARY KEY, owner TEXT NOT NULL, content TEXT NOT NULL)")

    def create(self, owner, task, criteria, tools):
        sid = uuid.uuid4().hex
        content = dict(task=task, success_criteria=criteria, tools=tools, turns=[], summary="", created_at=time.time())
        with self.connect() as c:
            c.execute("INSERT INTO agent_sessions VALUES (?,?,?)", (sid, owner, encode(content)))
        return {"session_id": sid, **content}

    def session(self, sid, owner):
        with self.connect() as c:
            row = c.execute("SELECT * FROM agent_sessions WHERE id=? AND owner=?", (sid, owner)).fetchone()
        if not row:
            raise HTTPException(404, "会话不存在")
        return json.loads(row["content"])

    def save_turn(self, sid, owner, question, result):
        # Store bounded conversation text; raw evidence remains in run traces.
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT content FROM agent_sessions WHERE id=? AND owner=?", (sid, owner)).fetchone()
            if not row: raise HTTPException(404, "会话不存在")
            data = json.loads(row[0])
            data["turns"].append({"question": question[:1000], "answer": result.get("answer", "")[:2000]})
            while len(data["turns"]) > 6:
                old = data["turns"].pop(0)
                data["summary"] = (data["summary"] + "\n历史对话（非当前证据）：" + encode(old))[-4000:]
            c.execute("UPDATE agent_sessions SET content=? WHERE id=?", (encode(data), sid))

    def run(self, sid, content, run_id=None):
        rid = run_id or uuid.uuid4().hex
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO agent_runs VALUES (?,?,?)", (rid, sid, encode(content)))
        return rid

    def request(self, sid, change):
        pid = uuid.uuid4().hex
        content = {**change, "status": "pending", "expires_at": time.time() + 600}
        content["digest"] = hashlib.sha256(encode(content).encode()).hexdigest()
        with self.connect() as c:
            c.execute("INSERT INTO agent_permissions VALUES (?,?,?)", (pid, sid, encode(content)))
        return {"permission_id": pid, **content}
