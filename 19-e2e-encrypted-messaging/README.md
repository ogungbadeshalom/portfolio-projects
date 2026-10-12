# echat — End-to-End Encrypted Messaging (TypeScript + WebSockets)

A runnable, minimal-but-honest E2E messaging implementation:

- **X3DH** key agreement (libsodium) so a session is established without ever
  sharing a secret.
- **Double Ratchet** for per-message forward secrecy + message-key skipping.
- A **relay server that stores only ciphertext.** It never has the keys and
  never parses message content; it just relays/stores opaque base64 blobs.
- **WebSocket** real-time delivery notices + HTTP polling fallback.
- Real libsodium crypto throughout — no invented/hand-rolled ciphers.

> A production UI would be a Vite + React app storing keys in IndexedDB. For
> portability this repo ships the full protocol engine (`shared/` + `client/`)
> with a thin CLI/HTTP client instead of the browser shell. Same protocol, testable
> headlessly. The deviation from CLAUDE.md is noted below.

## Layout

```
shared/            # protocol + all crypto (libsodium)
  crypto.ts        # X25519, Ed25519, X3DH, keyed-BLAKE2b KDF, AEAD, random
  session.ts       # prekey bundles + X3DH handshake + per-peer ratchet mgmt
  ratchet.ts       # the Double Ratchet state machine (+ skip-message-keys)
  protocol.ts      # wire types (ciphertext blob, header, notice)
server/            # untrusted relay — stores ciphertext only
  main.ts          # Node http + ws relay
  db.ts            # in-memory store (ciphertext blinding tested)
client/            # protocol client (what a React UI would call)
  client.ts        # register / fetch bundle / handshake / send / receive / decrypt
tests/             # node:test functional suite (runs on compiled dist/)
```

## Prereqs

- Node.js 20+ (uses global `fetch`)
- npm

## Install, build, test

```bash
npm install
npm run build        # tsc -> dist/
npm test             # build + run node:test functional suite
npm run typecheck    # strict type-only check, no emit
npm run start:server # start relay on port 8080 (or $PORT)
```

## Test coverage (`npm test`)

1. **Registration** — two clients upload prekey bundles.
2. **X3DH handshake** — Alice fetches Bob's bundle and both derive the same
   root key (verified implicitly by decryption succeeding).
3. **Round-trip** — Alice sends; the relay stores base64 ciphertext; Bob fetches
   and decrypts to the original plaintext; Bob replies; Alice decrypts.
4. **Ciphertext-only server** — asserts stored/relayed rows are base64 and that
   the plaintext string never appears in any server payload.
5. **Integrity** — flipping one ciphertext byte fails AEAD auth (returns null).
6. **Out-of-order** — 5 messages delivered out of order still decrypt via
   skip-message-keys.

## Honest notes / deviations from CLAUDE.md

- **KDF**: libsodium-wrappers 0.8.4 does **not** expose HKDF-SHA256 in this
  build, so the Double Ratchet KDF + X3DH SK derivation use **keyed BLAKE2b**
  (`crypto_generichash`) — the RFC 7693 KDF, and the same family the original
  Signal prototype used. It is not a hand-rolled cipher; it's a published KDF
  over libsodium primitives.
- **UI**: no Vite/React shell. `client/` is the protocol client; a real browser
  UI would wrap the exact same `session`/`crypto` API. Keys are in memory, not
  IndexedDB (IndexedDB is browser-only; `KeyRecord` is serializable so a
  browser storage + password-wrapping layer is a drop-in).
- **Signatures**: identity keys are Ed25519 that sign the signed prekey and the
  X3DH init bundle; the X25519 twin is derived via libsodium's
  `ed25519_pk/sk_to_curve25519` (standard Signal practice).
- **Storage**: in-memory instead of SQLite, so the test is hermetic and has no
  external service. Swapping in SQLite only changes `server/db.ts`.
- **One-time prekeys** are consumed exactly once (removed from both server and
  responder store).
- Server logging is intentionally minimal (never logs ciphertext).

## Shared-secret flow (why the server can't read)

Server only learns: `sender`, `recipient`, `timestamp`, and the rarefied
public/opaque blob `{ header, nonce, ciphertext }`. The keys to decrypt it are
derived on Alice/Bob's devices via Diffie-Hellman (X25519) over the prekey
bundle — the server has none of the private keys and cannot recover anything
from the base64 blobs it stores.

```
Alice ──(no secret)──▶ Relay ──(no secret)──▶ Bob
       ik/pub + ciphertext blob          ciphertext blob
```