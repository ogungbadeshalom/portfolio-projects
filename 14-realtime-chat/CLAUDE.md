# Real-Time Chat (WebSockets)

## Project Title
Real-Time Chat Application (FastAPI + WebSockets)

## Goal
A real-time chat app. Multiple users join rooms, send messages, see who's online, see typing indicators. Persistent message history.

## Why this project
WebSockets are how modern apps do real-time. Teaches: connection management, broadcasting, presence, message persistence, scaling considerations.

## What You Build

```
POST   /api/rooms                      # create room
GET    /api/rooms                      # list rooms
GET    /api/rooms/{id}/messages        # message history (paginated)
POST   /api/auth/login                 # JWT auth
WS     /ws/rooms/{id}                  # WebSocket connection
```

WebSocket protocol (JSON messages):
```
{ "type": "message", "user": "alice", "text": "hello", "ts": 1234567890 }
{ "type": "typing", "user": "alice" }
{ "type": "presence", "online": ["alice", "bob"] }
{ "type": "join", "user": "alice" }
{ "type": "leave", "user": "bob" }
```

Web UI at `http://localhost:8000/`:
- Room list + create
- Live message feed (auto-scroll, typing indicator)
- Online users list
- Login screen (simple JWT)

## Tech
- **Python 3.11+**
- **FastAPI** (web + WebSocket support)
- **websockets** library (or FastAPI's built-in)
- **SQLAlchemy** + **SQLite** (messages, users, rooms)
- **JWT** auth (PyJWT)
- **Vanilla HTML + WebSocket client** (or HTMX for partial UI)

## Architecture

```
chat/
├── chat/
│   ├── __init__.py
│   ├── main.py             # FastAPI entry
│   ├── ws.py               # WebSocket connection manager
│   ├── models.py           # User, Room, Message, RoomMembership
│   ├── auth.py             # JWT token generation/verification
│   ├── database.py
│   ├── routes/
│   │   ├── auth.py         # POST /api/auth/login
│   │   ├── rooms.py        # /api/rooms CRUD
│   │   └── messages.py     # /api/rooms/{id}/messages
│   ├── ws_handlers/
│   │   ├── connection.py   # connect/disconnect logic
│   │   ├── broadcast.py    # send to all in room
│   │   ├── presence.py     # online tracking
│   │   └── typing.py       # typing indicators
│   ├── templates/
│   │   ├── login.html
│   │   ├── rooms.html
│   │   └── chat.html
│   └── static/
│       ├── chat.js         # WebSocket client
│       └── style.css
├── tests/
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — User (id, username, password_hash), Room (id, name, created_by), Message (id, room_id, user_id, text, created_at), RoomMembership (user_id, room_id, joined_at)
2. **`database.py`** — async engine + session
3. **`auth.py`** — JWT token generation, password hashing (bcrypt), `get_current_user` dep
4. **`ws.py`** — `ConnectionManager` class tracking active connections per room
5. **`routes/auth.py`** — login endpoint, returns JWT
6. **`routes/rooms.py`** — CRUD for rooms
7. **`routes/messages.py`** — fetch message history (paginated, last 50)
8. **`ws.py`** — WebSocket endpoint `/ws/rooms/{id}` with auth via JWT in query param
9. **`ws_handlers/`** — handle message/typing/presence events, broadcast to room
10. **Templates** — login, rooms list, chat room

## Requirements

- JWT auth (token in `Authorization: Bearer` for HTTP, query param for WS)
- WebSocket auth: JWT in `?token=...` query param
- Messages persist to SQLite (survive server restart)
- Typing indicators: send `{type: "typing"}`, broadcast to room (not echoed back to sender)
- Presence: send `online` list on join, update on every disconnect
- Message ordering: chronological, oldest at top
- Rate limiting: max 10 messages per minute per user
- Max message length: 1000 chars (return error if exceeded)
- Server-side validation of message text (no HTML, sanitized)
- Reconnection support: client can reconnect with last_seen_message_id, server sends missed messages

## Code Standards

- All WebSocket handlers are async
- ConnectionManager uses `dict[room_id, set[WebSocket]]` for tracking
- Messages validated server-side (length, content)
- Rate limiting uses Redis or in-memory dict with timestamps
- All WS sends wrapped in try/except (handle closed connections)
- JSON messages use Pydantic for validation
- Errors logged with user_id + room_id context

## Verification

```bash
# Start server
uvicorn chat.main:app --port 8000

# Open 2 browsers at http://localhost:8000/
# Login as different users, send messages, verify real-time delivery

# Test with wscat (CLI WebSocket client)
wscat -c ws://localhost:8000/ws/room-1?token=JWT_TOKEN
> {"type":"message","text":"hello"}

# Run tests
pytest tests/ -v --asyncio-mode=auto
```

## Stretch Goals

- File/image uploads in messages (link to file storage)
- Message reactions (emoji)
- Reply to message (threading)
- Read receipts
- Push notifications when offline
- Voice/video calls (WebRTC)
- End-to-end encryption
- Multiple rooms, room permissions, private messages
- Search across message history

## What You'll Learn

- WebSocket protocol (RFC 6455)
- Connection management at scale
- Broadcasting patterns
- Presence tracking
- JWT auth for both HTTP and WebSocket
- Async message handling
- Rate limiting patterns

## Time Estimate
10-14 hours for MVP. 20-28 hours with presence + typing + reconnect + persistence + tests.