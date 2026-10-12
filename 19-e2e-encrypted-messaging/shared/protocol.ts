/**
 * shared/protocol.ts
 *
 * Wire protocol types shared between the client and the server.
 *
 * The server treats every message body AND session-establishment record as an
 * opaque byte blob. It never parses inside `content` / `ciphertext`, so it
 * cannot read plaintext. All bodies are base64-encoded ciphertext produced by
 * libsodium.
 */

/** Cryptographic identities and one-time prekeys for X3DH. */
export interface Identity {
  /** Stable username / user id the server addresses messages to. */
  identityKey: string;
  /** base64 X25519 public key (identity key). */
  ik: string;
  /** base64 signed X25519 public key (signed prekey), part of the bundle. */
  spk: string;
  /** base64 signature (over the signed prekey) made by the identity key. */
  spkSig: string;
  /** base64 X25519 public key (ratchet initiator key X25519). Part of DH1 compute. */
  ek?: string;
  /** One-time prekeys: a map base64 otkId -> base64 public key. */
  otks?: Record<string, string>;
}

/** The bundle a user uploads to the server. */
export interface PrekeyBundle {
  identityKey: string;
  ik: string;
  spk: string;
  spkSig: string;
  otkId: string;
  otk: string;
}

/** Signed prekey upload payload. */
export interface UploadKeysRequest {
  identityKey: string;
  /** base64 X25519 identity public key. */
  ik: string;
  /** base64 X25519 signed-prekey public key. */
  spk: string;
  /** base64 ed25519-style signature over spk, produced by the identity key. */
  spkSig: string;
  /** one-time prekeys to publish: base64 id -> base64 public key. */
  otks: Record<string, string>;
}

/** Ciphertext body stored on the server. Server stores this verbatim. */
export interface StoredMessage {
  id: string;
  /** base64 header (Double-Ratchet header: DH ratchet public key + PN + N). */
  header: string;
  /** base64 nonce. */
  nonce: string;
  /** base64 AEAD ciphertext (XChaCha20-Poly1305 in libsodium terms). */
  ciphertext: string;
  sender: string;
  recipient: string;
  /** ms epoch timestamp. */
  timestamp: number;
}

/**
 * The Double Ratchet message format that travels over the wire.
 * `header` `nonce` `ciphertext` are collectively the opaque blob the server
 * relays. The server only reads `sender` / `recipient` / `timestamp`.
 */
export interface RatchetMessage {
  /** base64 Double-Ratchet header: { dh, pn, n } */
  header: string;
  /** base64 24-byte nonce */
  nonce: string;
  /** base64 ciphertext */
  ciphertext: string;
}

/** Types of incoming-decrypt results. */
export type DecryptResult =
  | { ok: true; plaintext: string }
  | { ok: false; error: string };

/** WebSocket delivery notice the server relays (metadata only). */
export interface WsNotice {
  kind: 'message';
  messageId: string;
  sender: string;
  recipient: string;
  timestamp: number;
}