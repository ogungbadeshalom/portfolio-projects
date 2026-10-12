# End-to-End Encrypted Messaging

## Project Title
End-to-End Encrypted Messaging (TypeScript + WebSockets)

## Goal
A secure messaging app where messages are encrypted on the sender's device, sent as ciphertext, and only decrypted on the recipient's device. Server never sees plaintext.

## Why this project
Cryptography in practice. Teaches: key exchange (X3DH), double ratchet algorithm, key management, secure random, libsodium, identity verification.

## Why this matters
Signal Protocol, WhatsApp, iMessage all use similar techniques. Building one teaches you how real E2E messaging works.

## What You Build

A web-based E2E messaging app:
1. Generate identity keypair on signup (stored in browser IndexedDB)
2. User discovers other users via public key server
3. Initiate session via X3DH key exchange (prekey bundle)
4. Send messages encrypted with Double Ratchet
5. Messages stored encrypted on server (server can't read)
6. Recipients decrypt on their device

```
POST   /api/keys/upload              # upload prekey bundle
GET    /api/keys/{user_id}          # fetch someone's prekey bundle
POST   /api/keys/{user_id}/prekey   # claim one-time prekey
POST   /api/messages                # send encrypted message (server stores, can't read)
GET    /api/messages?since=...       # fetch new messages
WS     /ws                          # real-time delivery
```

Web UI:
- Identity creation (display fingerprint as QR)
- Contact list (other registered users)
- Conversation view (encrypted messages decrypt in browser)
- New conversation (scan QR of contact's identity)

## Tech
- **TypeScript** (strict mode)
- **Next.js** or **Vite + React** (frontend)
- **libsodium-wrappers** (cryptography primitives)
- **Web Crypto API** (browser-native crypto)
- **WebSocket** (real-time delivery)
- **Node.js + Fastify** (server, just stores ciphertext)
- **SQLite** or **PostgreSQL** (encrypted message storage)

## Architecture

```
echat/
├── echat/
│   ├── client/                # browser app
│   │   ├── index.html
│   │   ├── src/
│   │   │   ├── crypto.ts      # X3DH + Double Ratchet
│   │   │   ├── identity.ts    # keypair generation, fingerprint
│   │   │   ├── session.ts     # session management
│   │   │   ├── messages.ts    # encrypt/decrypt
│   │   │   └── ui.ts          # React UI
│   │   └── package.json
│   ├── server/                # stores ciphertext only
│   │   ├── main.ts            # Fastify server
│   │   ├── routes/
│   │   │   ├── keys.ts        # prekey bundles
│   │   │   ├── messages.ts    # ciphertext storage
│   │   │   └── ws.ts          # real-time delivery
│   │   ├── models.ts
│   │   └── db.ts
│   ├── shared/                # shared types
│   │   └── protocol.ts        # message format, handshake
│   └── tests/
└── CLAUDE.md
```

## Build Order

1. **`shared/protocol.ts`** — TypeScript types for messages, prekeys, ciphertext format
2. **`client/crypto.ts`** — libsodium wrapper: keypair generation, X3DH handshake, Double Ratchet
3. **`client/identity.ts`** — Generate identity keypair, store in IndexedDB, display fingerprint as QR
4. **`server/routes/keys.ts`** — upload prekey bundle, fetch prekey bundle, claim one-time prekey
5. **`client/session.ts`** — Initiate session with contact's prekey bundle, run X3DH, establish root key, start Double Ratchet
6. **`server/routes/messages.ts`** — POST encrypted message (server stores opaque ciphertext), GET new messages since timestamp
7. **`client/messages.ts`** — Encrypt outgoing with Double Ratchet, decrypt incoming, handle out-of-order delivery
8. **`server/routes/ws.ts`** — WebSocket notifies recipient of new message (server only sees ciphertext metadata: sender_id, recipient_id, timestamp)
9. **`client/ui.ts`** — React UI for contacts list, conversation view, QR scan for adding contacts
10. **Tests** — key generation, X3DH handshake, encrypt/decrypt round-trip, out-of-order delivery

## Requirements

- X3DH key exchange protocol (matches Signal spec)
- Double Ratchet algorithm (forward secrecy + post-compromise security)
- Server NEVER sees plaintext (only ciphertext)
- Identity verification via safety numbers / fingerprint
- Prekey bundles stored on server (one-time prekeys consumed)
- Out-of-order message delivery handled (skip message keys)
- Session resumption after offline
- Message deletion (forward to recipient, then delete on server)
- WebSocket for real-time delivery (fallback to polling)
- All crypto operations use libsodium (not custom crypto)

## Code Standards

- TypeScript strict mode, no `any`
- All crypto via libsodium (NEVER custom crypto)
- Random values from `crypto.getRandomValues()` (cryptographically secure)
- Key storage: IndexedDB with encryption-at-rest (key wrapped by password)
- Server treats all message bodies as opaque (no parsing of "content")
- Prekey consumption: atomic Redis SETNX or DB unique constraint
- Message deletion: hard delete (no soft delete in audit log for E2E)
- Type-safe protocol messages (no string concatenation, use Zod or TypeBox)
- No logging of cryptographic material (keys, ciphertext)

## Verification

```bash
# Start server
cd echat/server && npm start

# Start client
cd echat/client && npm run dev

# Test in 2 browsers:
# 1. Browser A: signup → get fingerprint → display QR
# 2. Browser B: signup → display QR
# 3. A: scan B's QR → conversation starts → send message
# 4. B: receives message, can decrypt and read

# Verify server can't read:
sqlite3 messages.db "SELECT content FROM messages LIMIT 1"
# Should show base64 ciphertext, not plaintext

# Run tests
cd echat && npm test
```

## Stretch Goals

- Group messaging (Sender Keys)
- Voice/video calls (WebRTC with DTLS-SRTP)
- Disappearing messages (server enforces TTL)
- Multi-device sync (sessions per device)
- Sealed sender (hide sender identity from server)
- Post-compromise security (double ratchet with future ratchet)
- Verified safety numbers (out-of-band verification)
- Contact verification via QR scan
- Encrypted attachments (file encryption before upload)

## What You'll Learn

- X3DH key exchange protocol
- Double Ratchet algorithm (Signal Protocol)
- libsodium cryptographic primitives
- Identity-based encryption
- Public key infrastructure (PKI)
- Forward secrecy + post-compromise security
- IndexedDB for client-side key storage
- Server-as-untrusted-relay architecture

## Time Estimate
20-30 hours for MVP. 50-80 hours for production-grade with group messaging + verified UI + multi-device.

## References

- Signal Protocol spec: https://signal.org/docs/
- X3DH: https://signal.org/docs/specifications/x3dh/
- Double Ratchet: https://signal.org/docs/specifications/doubleratchet/
- libsodium docs: https://doc.libsodium.org/