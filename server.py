import sqlite3, uuid, hashlib, json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Dict, List

app = FastAPI()
DB_PATH = "server_messenger.db"

def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY, username TEXT UNIQUE, display_name TEXT,
            password_hash TEXT, email TEXT, avatar TEXT
        );
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT, receiver_id TEXT,
            kind TEXT, content TEXT, duration REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
init_db()

def hash_p(p): return hashlib.sha256(p.encode()).hexdigest()

class UserReg(BaseModel):
    username: str; display_name: str; password: str; email: str

class UserLogin(BaseModel):
    username: str; password: str

@app.post("/register")
def register(u: UserReg):
    uid = str(uuid.uuid4())
    try:
        with sqlite3.connect(DB_PATH) as c:
            c.execute("INSERT INTO users(id, username, display_name, password_hash, email) VALUES(?,?,?,?,?)",
                      (uid, u.username, u.display_name, hash_p(u.password), u.email))
        return {"status": "ok", "id": uid}
    except: return {"status": "error", "msg": "Логин занят"}

@app.post("/login")
def login(u: UserLogin):
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM users WHERE username=? AND password_hash=?", (u.username, hash_p(u.password))).fetchone()
        if row: return {"status": "ok", "user": dict(row)}
    return {"status": "error", "msg": "Неверный логин/пароль"}

@app.get("/users")
def get_users():
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT id, username, display_name, avatar FROM users").fetchall()]

@app.get("/messages/{u1}/{u2}")
def get_msgs(u1: str, u2: str):
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("""SELECT * FROM messages 
                            WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?) 
                            ORDER BY id""", (u1, u2, u2, u1)).fetchall()
        return [dict(r) for r in rows]

# Активные подключения
active_connections: Dict[str, WebSocket] = {}

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    active_connections[user_id] = websocket
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            # msg = {"receiver": "...", "kind": "text", "content": "...", "duration": 0}
            with sqlite3.connect(DB_PATH) as c:
                c.execute("INSERT INTO messages(sender_id, receiver_id, kind, content, duration) VALUES(?,?,?,?,?)",
                          (user_id, msg["receiver"], msg["kind"], msg["content"], msg.get("duration", 0)))
            
            # Отправляем получателю
            if msg["receiver"] in active_connections:
                await active_connections[msg["receiver"]].send_text(json.dumps({
                    "sender": user_id, "kind": msg["kind"], "content": msg["content"], "duration": msg.get("duration", 0)
                }))
    except WebSocketDisconnect:
        del active_connections[user_id]
