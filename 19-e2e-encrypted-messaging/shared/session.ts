/**
 * shared/session.ts
 *
 * End-to-end session layer: X3DH handshake + Double Ratchet, kept in `shared/`
 * so a browser-style client and the test harness use the same pure-libsodium
 * code (this mirrors CLAUDE.md's `client/session.ts` + `client/messages.ts`).
 *
 * Identity model (matches Signal):
 *   - identity key = Ed25519 keypair (signed prekey verification + signing)
 *   - X25519 "twin" derived for DH via crypto_sign_ed25519_pk/sk_to_curve25519
 *   - signed prekey  = fresh X25519 keypair, signed by the Ed25519 identity key
 *   - one-time prekeys = fresh X25519 keypairs (consumed once, then deleted)
 *
 * Keys live in memory here; the CLAUDE.md calls for IndexedDB with
 * encryption-at-rest, which a real deploy would supply around this record.
 */

import * as C from './crypto';
import { DoubleRatchet } from './ratchet';
import type { RatchetHeader } from './crypto';

/** Serialized, uploadable prekey bundle (matches server /api/keys/upload). */
export interface PrekeyBundleWire {
  identityKey: string; // owner username
  ik: string; // base64 Ed25519 identity public key
  spk: string; // base64 X25519 signed-prekey public key
  spkSig: string; // base64 Ed25519 signature over spk bytes
  otkId: string; // one-time prekey identifier
  otk: string; // base64 X25519 one-time-prekey public key
}

/** Alice's X3DH initiation bundle (sent as the body of the first message). */
export interface InitBundleWire {
  ik: string; // base64 Ed25519 identity public key (Alice)
  ek: string; // base64 X25519 ephemeral public key (Alice)
  signature: string; // base64 Ed25519 signature over the context below
  otkId: string | null; // the one-time prekey id Alice used on Bob's bundle
}

export interface KeyRecord {
  identityEd: C.IdentityKeys;
  signedPreKey: C.SignedPreKey;
  /** unconsumed one-time prekeys, keyed by base64 id. */
  oneTimePreKeys: Map<string, C.KeyPairX25519>;
}

export class UserSession {
  readonly name: string;
  readonly record: KeyRecord;
  private ratchets = new Map<string, DoubleRatchet>(); // keyed by peer's ikEd b64

  private constructor(name: string, record: KeyRecord) {
    this.name = name;
    this.record = record;
  }

  static async create(name: string): Promise<UserSession> {
    await C.initSodium();
    const identityEd = C.generateIdentityKeys();
    const spk = C.generateKeyPair();
    const signedPreKey: C.SignedPreKey = {
      keyPair: spk,
      signature: C.signDetached(spk.publicKey, identityEd.secret),
    };
    const otks = new Map<string, C.KeyPairX25519>();
    for (let i = 0; i < 10; i++) {
      const kp = C.generateKeyPair();
      otks.set(C.toBase64(C.randomBytes(8)), kp);
    }
    return new UserSession(name, { identityEd, signedPreKey, oneTimePreKeys: otks });
  }

  // ------------------------------------------------------------ helpers
  get identityXPublic(): Uint8Array {
    return C.identityPubToX25519(this.record.identityEd.pub);
  }
  get identityXSecret(): Uint8Array {
    return C.identitySecretToX25519(this.record.identityEd.secret);
  }
  /** base64 Ed25519 identity public key (the user's stable public id). */
  get identityEdPubB64(): string {
    return C.toBase64(this.record.identityEd.pub);
  }

  // ------------------------------------------------------------ register
  /** Publish a bundle : hands out one one-time prekey (kept pending until consumed). */
  makeBundle(peerName: string): PrekeyBundleWire {
    const firstId = this.record.oneTimePreKeys.keys().next().value as string;
    const otk = this.record.oneTimePreKeys.get(firstId);
    if (!otk) throw new Error(`${this.name}: no one-time prekeys left`);
    return {
      identityKey: peerName, // addressed-to owner (server keys bundles by owner separately)
      ik: C.toBase64(this.record.identityEd.pub),
      spk: C.toBase64(this.record.signedPreKey.keyPair.publicKey),
      spkSig: C.toBase64(this.record.signedPreKey.signature),
      otkId: firstId,
      otk: C.toBase64(otk.publicKey),
    };
  }

  /**
   * X3DH initiator (Alice). Verifies Bob's signed-prekey signature, computes
   * the 3XDH shared secret, and initialises a Double Ratchet.
   * Returns the init bundle ALICE must send Bob, plus the peer key (Bob's ikEd
   * b64) to use when calling `send()` afterwards.
   */
  async initiate(bundle: PrekeyBundleWire): Promise<{ initBody: string; peerKey: string }> {
    const bobIkEd = C.fromBase64(bundle.ik);
    const bobIkX = C.identityPubToX25519(bobIkEd);
    const spkPub = C.fromBase64(bundle.spk);
    const sigOk = C.verifyDetached(
      C.fromBase64(bundle.spkSig),
      spkPub,
      bobIkEd,
    );
    if (!sigOk) throw new Error(`${this.name}: Bob's signed-prekey signature invalid`);

    const otkPub = bundle.otk ? C.fromBase64(bundle.otk) : null;

    // Build Alice's init bundle = first message body.
    const ek = C.generateKeyPair();
    const toSign = this.concatInitContext(this.identityXPublic, spkPub, otkPub ?? null);
    const signature = C.signDetached(toSign, this.record.identityEd.secret);

    const sk = C.x3dhSharedSecret(
      this.identityXSecret,
      ek,
      bobIkX,
      spkPub,
      otkPub,
    );

    const ratchet = DoubleRatchet.initiator(sk, spkPub, {
      ourIdentityPub: this.identityXPublic,
      theirIdentityPub: bobIkX,
    });
    const peerKey = C.toBase64(bobIkEd);
    this.ratchets.set(peerKey, ratchet);
    return { initBody: this.serializeInit(bobIkX, ek, signature, bundle.otkId), peerKey };
  }

  /**
   * X3DH responder (Bob). Verifies Alice's signature over the init context,
   * recomputes the shared secret, and initialises his Double Ratchet.
   * Returns the peer (Alice) ikEd b64 used to key messages.
   */
  async receiveInit(init: InitBundleWire): Promise<string> {
    const aliceIkEd = C.fromBase64(init.ik);
    const aliceIkX = C.identityPubToX25519(aliceIkEd);
    const aliceEkX = C.fromBase64(init.ek);
    const spkPub = this.record.signedPreKey.keyPair.publicKey;

    // Look up + consume the one-time prekey Alice used (if any).
    let otk: C.KeyPairX25519 | null = null;
    if (init.otkId != null) {
      otk = this.record.oneTimePreKeys.get(init.otkId) ?? null;
      if (otk) {
        this.record.oneTimePreKeys.delete(init.otkId); // exactly-once use
      }
    }

    // Verify Alice's identity signature over (peer-ctx, spk, otk).
    const toVerify = this.concatInitContext(aliceIkX, spkPub, otk ? otk.publicKey : null);
    const ok = C.verifyDetached(C.fromBase64(init.signature), toVerify, aliceIkEd);
    if (!ok) throw new Error(`${this.name}: Alice's init signature invalid`);

    const sk = C.x3dhSharedSecretResponder(
      this.identityXSecret, // IKB secret
      this.record.signedPreKey.keyPair.secretKey, // SPKB secret
      otk ? otk.secretKey : null, // OTKB secret
      aliceIkX, // IKa pub
      aliceEkX, // EKa pub
    );

    const ratchet = DoubleRatchet.responder(sk, this.record.signedPreKey.keyPair.secretKey, {
      ourIdentityPub: this.identityXPublic,
      theirIdentityPub: aliceIkX,
    });
    const key = C.toBase64(aliceIkEd);
    this.ratchets.set(key, ratchet);
    return key;
  }

  private concatInitContext(
    peerIkX: Uint8Array,
    spkPub: Uint8Array,
    otkPub: Uint8Array | null,
  ): Uint8Array {
    const parts = [peerIkX, spkPub];
    if (otkPub) parts.push(otkPub);
    const total = parts.reduce((a, b) => a + b.length, 0);
    const out = new Uint8Array(total + 1);
    let i = 0;
    out[i++] = otkPub ? 1 : 0;
    for (const p of parts) {
      out.set(p, i);
      i += p.length;
    }
    return out;
  }

  private serializeInit(
    peerIkX: Uint8Array,
    ek: C.KeyPairX25519,
    signature: Uint8Array,
    otkId: string | null,
  ): string {
    void peerIkX;
    const init: InitBundleWire = {
      ik: C.toBase64(this.record.identityEd.pub),
      ek: C.toBase64(ek.publicKey),
      signature: C.toBase64(signature),
      otkId,
    };
    return JSON.stringify(init);
  }

  // ------------------------------------------------------------ messages
  /** Encrypt to peer by their identity-Ed b64. */
  send(peerIkEdB64: string, plaintext: string): { header: RatchetHeader; nonce: string; ciphertext: string } {
    const r = this.ratchets.get(peerIkEdB64);
    if (!r) throw new Error(`${this.name}: no session with peer`);
    return r.encrypt(plaintext);
  }

  decrypt(peerIkEdB64: string, header: RatchetHeader, nonce: string, ciphertext: string): string | null {
    const r = this.ratchets.get(peerIkEdB64);
    if (!r) return null;
    return r.decrypt(header, nonce, ciphertext);
  }

  hasSession(peerIkEdB64: string): boolean {
    return this.ratchets.has(peerIkEdB64);
  }
}