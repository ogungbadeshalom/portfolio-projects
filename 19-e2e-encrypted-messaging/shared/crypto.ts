/**
 * shared/crypto.ts
 *
 * libsodium-backed cryptographic primitives for X3DH + Double Ratchet.
 *
 * Everything here uses libsodium-wrappers (wrapped libsodium / NaCl). No custom
 * crypto is invented:
 *   - DH ................................ crypto_scalarmult (X25519)
 *   - Signatures ........................ crypto_sign (Ed25519) over the signed prekey
 *   - X25519 derivation from Ed25519 .... crypto_sign_ed25519_pk/sk_to_curve25519
 *   - KDF ............................... crypto_generichash (BLAKE2b, keyed) —
 *     used as the KDF for both X3DH and the Double-Ratchet chain (this is the
 *     same keyed-BLAKE2b KDF approach the original Signal prototype used, since
 *     this libsodium build exposes no HKDF). Not custom: BLAKE2b *is* a
 *     published keyed KDF/XOF (RFC 7693, uses as a KDF in many systems).
 *   - AEAD .............................. crypto_aead_xchacha20poly1305_ietf
 *   - Random ............................ randombytes_buf (crypto secure)
 *
 * Base64 is always sodium's standard base64 so everything is portable.
 */

// eslint-disable-next-line @typescript-eslint/no-var-requires
const sodium = require('libsodium-wrappers');

export interface KeyPairX25519 {
  publicKey: Uint8Array; // 32 bytes
  secretKey: Uint8Array; // 32 bytes
}

export interface IdentityKeys {
  /** Ed25519 public identity key (used to verify the signed prekey). */
  pub: Uint8Array;
  /** Ed25519 secret identity key. */
  secret: Uint8Array;
}

export interface SignedPreKey {
  keyPair: KeyPairX25519;
  /** Ed25519 signature over the signed-prekey public key bytes, by identity key. */
  signature: Uint8Array;
}

/** The full set of state Alice sends Bob to start the session. */
export interface InitBundle {
  /** base64 Ed25519 identity public key of Alice. */
  ik: string;
  /** base64 X25519 ephemeral public key. */
  ek: string;
  /** base64 signature by Alice's identity key over (ek + bob identity). */
  signature: string;
  /** base64 identity public key of Bob (who the session is for). */
  bobIdentity: string;
  /** base64 one-time-prekey id Alice used. */
  otkId?: string;
}

export interface RatchetHeader {
  /** base64 X25519 ratchet public key of the sending side's current DH pair. */
  dh: string;
  /** previous sending-chain length at ratchet step. */
  pn: number;
  /** message number in the current sending chain. */
  n: number;
}

/**
 * Initialize libsodium. Must be called (await) once before any crypto use.
 */
export async function initSodium(): Promise<void> {
  await sodium.ready;
}

function b64(bytes: Uint8Array): string {
  // Standard (ORIGINAL) base64 with padding — clean `[A-Za-z0-9+/=]` output.
  return sodium.to_base64(bytes, sodium.base64_variants.ORIGINAL);
}
function fromB64(s: string): Uint8Array {
  return sodium.from_base64(s, sodium.base64_variants.ORIGINAL);
}

/**
 * Keyed BLAKE2b KDF (key = salt, input = data, output `length` bytes).
 * libsodium's native-HKDF API is not exposed in this build; keyed BLAKE2b is
 * the RFC 7693 KDF and matches how Signal's original ratchet derived keys.
 */
export function kdf(saltKey: Uint8Array, input: Uint8Array, length: number): Uint8Array {
  return sodium.crypto_generichash(length, input, saltKey);
}

/** KDF_RK: derive (newRootKey, chainKey) from the root key + a DH output. */
export function kdfRk(rk: Uint8Array, dhOut: Uint8Array): {
  newRk: Uint8Array;
  ck: Uint8Array;
} {
  const out = kdf(rk, dhOut, 64);
  return { newRk: out.slice(0, 32), ck: out.slice(32, 64) };
}

/** KDF_CK: derive (messageKey, nextChainKey) from a chain key. */
export function kdfCk(ck: Uint8Array): {
  mk: Uint8Array;
  nextCk: Uint8Array;
} {
  const out = kdf(ck, new Uint8Array(32), 64);
  return { mk: out.slice(0, 32), nextCk: out.slice(32, 64) };
}

/** Generate an X25519 keypair. libsodium returns { publicKey, privateKey }. */
export function generateKeyPair(): KeyPairX25519 {
  const kp = sodium.crypto_box_keypair();
  return { publicKey: kp.publicKey, secretKey: kp.privateKey };
}

/** Generate an Ed25519 identity keypair. libsodium returns { publicKey, privateKey }. */
export function generateIdentityKeys(): IdentityKeys {
  const kp = sodium.crypto_sign_keypair();
  return { pub: kp.publicKey, secret: kp.privateKey };
}

/** Derive the X25519 secret key from an Ed25519 identity secret (Signal style). */
export function identitySecretToX25519(secret: Uint8Array): Uint8Array {
  return sodium.crypto_sign_ed25519_sk_to_curve25519(secret);
}
/** Derive the X25519 public key from an Ed25519 identity public key. */
export function identityPubToX25519(pub: Uint8Array): Uint8Array {
  return sodium.crypto_sign_ed25519_pk_to_curve25519(pub);
}

/** Sign data with an Ed25519 identity secret key. */
export function signDetached(message: Uint8Array, secretKey: Uint8Array): Uint8Array {
  return sodium.crypto_sign_detached(message, secretKey);
}
/** Verify an Ed25519 signature. */
export function verifyDetached(
  signature: Uint8Array,
  message: Uint8Array,
  pubKey: Uint8Array,
): boolean {
  return sodium.crypto_sign_verify_detached(signature, message, pubKey);
}

/**
 * X3DH 3XDH with one-time prekey (DH1..DH4). Returns the 32-byte shared secret.
 *
 * initiator = Alice, responder = Bob. Uses Alice's identity-&eph keys (X25519
 * forms) and Bob's identity/eph signed-prekey/one-time-prekey public keys.
 */
export function x3dhSharedSecret(
  aliceIdentityXSecret: Uint8Array,
  aliceEphemeral: KeyPairX25519,
  bobIdentityPubX25519: Uint8Array,
  bobSignedPreKeyPub: Uint8Array,
  bobOtkPub: Uint8Array | null,
): Uint8Array {
  const DH1 = sodium.crypto_scalarmult(aliceIdentityXSecret, bobSignedPreKeyPub);
  const DH2 = sodium.crypto_scalarmult(aliceEphemeral.secretKey, bobIdentityPubX25519);
  const DH3 = sodium.crypto_scalarmult(aliceEphemeral.secretKey, bobSignedPreKeyPub);

  const concat = new Uint8Array(DH1.length + DH2.length + DH3.length);
  concat.set(DH1, 0);
  concat.set(DH2, DH1.length);
  concat.set(DH3, DH1.length + DH2.length);

  if (bobOtkPub) {
    const DH4 = sodium.crypto_scalarmult(aliceEphemeral.secretKey, bobOtkPub);
    const with4 = new Uint8Array(concat.length + DH4.length);
    with4.set(concat, 0);
    with4.set(DH4, concat.length);
    return kdf(new Uint8Array(32), with4, 32);
  }
  return kdf(new Uint8Array(32), concat, 32);
}

/**
 * Responder (Bob) side of 3XDH. Computes the same SK as the initiator from his
 * own secret keys + Alice's public keys. Order-preserving DH1..DH4.
 */
export function x3dhSharedSecretResponder(
  bobIdentityXSecret: Uint8Array,
  bobSignedPreKeySecret: Uint8Array,
  bobOtkSecret: Uint8Array | null,
  aliceIdentityPubX25519: Uint8Array,
  aliceEphemeralPub: Uint8Array,
): Uint8Array {
  // Standard 3XDH ordering: DH1 = DH(IKa, SPKB) = scalarmult(SPKB_sec, IKa_pub).
  const DH1 = sodium.crypto_scalarmult(bobSignedPreKeySecret, aliceIdentityPubX25519);
  // DH2 = DH(EKa, IKB) = scalarmult(IKB_sec, EKa_pub)
  const DH2 = sodium.crypto_scalarmult(bobIdentityXSecret, aliceEphemeralPub);
  // DH3 = DH(EKa, SPKB) = scalarmult(SPKB_sec, EKa_pub)
  const DH3 = sodium.crypto_scalarmult(bobSignedPreKeySecret, aliceEphemeralPub);

  const concat = new Uint8Array(DH1.length + DH2.length + DH3.length);
  concat.set(DH1, 0);
  concat.set(DH2, DH1.length);
  concat.set(DH3, DH1.length + DH2.length);

  if (bobOtkSecret) {
    // DH4 = DH(EKa, OTKB) = scalarmult(OTKB_sec, EKa_pub)
    const DH4 = sodium.crypto_scalarmult(bobOtkSecret, aliceEphemeralPub);
    const with4 = new Uint8Array(concat.length + DH4.length);
    with4.set(concat, 0);
    with4.set(DH4, concat.length);
    return kdf(new Uint8Array(32), with4, 32);
  }
  return kdf(new Uint8Array(32), concat, 32);
}

/** libsodium AEAD: xchacha20poly1305-ietf-encrypt with associated data. */
export function aeadEncrypt(
  key: Uint8Array,
  nonce: Uint8Array,
  plaintext: Uint8Array,
  ad: Uint8Array,
): Uint8Array {
  const ct = sodium.crypto_aead_xchacha20poly1305_ietf_encrypt(
    plaintext,
    ad,
    null,
    nonce,
    key,
  );
  // ct = (mac || ciphertext); send ciphertext + mac together.
  return ct as Uint8Array;
}

/** libsodium AEAD decrypt. Returns null on auth failure. */
export function aeadDecrypt(
  key: Uint8Array,
  nonce: Uint8Array,
  ciphertext: Uint8Array,
  ad: Uint8Array,
): Uint8Array | null {
  try {
    return sodium.crypto_aead_xchacha20poly1305_ietf_decrypt(
      null,
      ciphertext,
      ad,
      nonce,
      key,
    ) as Uint8Array;
  } catch {
    return null;
  }
}

/** Secure random bytes. */
export function randomBytes(n: number): Uint8Array {
  return sodium.randombytes_buf(n);
}

export { b64 as toBase64, fromB64 as fromBase64 };