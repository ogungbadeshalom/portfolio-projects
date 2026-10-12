/**
 * shared/ratchet.ts
 *
 * Double Ratchet (Signal) with:
 *   - KDF chain (HKDF) with chain & message keys
 *   - DH ratchet step on receiving a new ratchet public key
 *   - skip-message-keys dict for out-of-order / missing messages
 *   - AEAD via libsodium xchacha20poly1305 with associated-data binding
 *
 * Implements both roles:
 *   - `DoubleRatchet.initiator(rootKey, theirInitDH)`: Alice. Holds the fresh
 *     DH key pair whose public key goes in the first header; `theirInitDH` is
 *     Bob's first ratchet key (Bob's signed prekey from X3DH).
 *   - `DoubleRatchet.responder(rootKey)`: Bob. Receives Alice's first DH key in
 *     the first message header and runs the first DH ratchet.
 */

import {
  aeadDecrypt,
  aeadEncrypt,
  generateKeyPair,
  kdfCk,
  kdfRk,
  randomBytes,
  toBase64,
  fromBase64,
  type KeyPairX25519,
} from './crypto';
import type { RatchetHeader } from './crypto';

const MAX_SKIP = 1000;
const AD_LEN = 32 + 32; // sender || recipient identity keys (x25519)

/** One-way chain of message keys derived from a chain key (CK). */
interface ChainState {
  ck: Uint8Array;
  /** skipped message keys: key = `${theirPubB64}_${n}` -> message key */
  skipped: Map<string, Uint8Array>;
  /** next message number to use for this chain. */
  n: number;
}

export interface RatchetOptions {
  ourIdentityPub: Uint8Array;
  theirIdentityPub: Uint8Array;
}

// Lazy libsodium access (avoids top-level ESM/CJS friction inside sync methods).
// Sodium is already ready because initSodium() is awaited before use.
function sodium(): any {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  return require('libsodium-wrappers');
}

/** Byte-wise lexicographic less-than (for canonical AD ordering). */
function lexLt(a: Uint8Array, b: Uint8Array): boolean {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    if (a[i] !== b[i]) return a[i] < b[i];
  }
  return a.length < b.length;
}

export class DoubleRatchet {
  private rootKey: Uint8Array;
  private DHs: KeyPairX25519; // our current DH ratchet key pair
  private DHr: Uint8Array | null; // their current DH ratchet public key
  private sendingChain: ChainState | null = null;
  private receivingChain: ChainState | null = null;
  private pn = 0; // length of previous sending chain (sent in next header)
  private ourIdentityPub: Uint8Array;
  private theirIdentityPub: Uint8Array;

  private constructor(
    rootKey: Uint8Array,
    opts: RatchetOptions,
    initialDHr: Uint8Array | null,
  ) {
    this.rootKey = rootKey;
    this.ourIdentityPub = opts.ourIdentityPub;
    this.theirIdentityPub = opts.theirIdentityPub;
    this.DHr = initialDHr;
    this.DHs = generateKeyPair();
  }

  static initiator(
    rootKey: Uint8Array,
    theirRatchetDH: Uint8Array,
    opts: RatchetOptions,
  ): DoubleRatchet {
    // Bob's first ratchet key is his signed prekey (the SPK from X3DH). Alice
    // knows it from the prekey bundle, so she can derive her FIRST sending chain
    // immediately, without waiting for any inbound message.
    const r = new DoubleRatchet(rootKey, opts, theirRatchetDH);
    const { newRk, ck } = kdfRk(r.rootKey, r.scalarmult(theirRatchetDH, r.DHs.secretKey));
    r.rootKey = newRk;
    r.sendingChain = { ck, skipped: new Map(), n: 0 };
    return r;
  }

  /**
   * Responder (Bob). `ourRatchetSecret` MUST be the secret key that pairs with
   * the public key Alice used as `theirRatchetDH` in `initiator` — i.e. Bob's
   * X3DH signed-prekey secret. Bob holds no sending chain yet; it is derived on
   * the first incoming header.
   */
  static responder(
    rootKey: Uint8Array,
    ourRatchetSecret: Uint8Array,
    opts: RatchetOptions,
  ): DoubleRatchet {
    const r = new DoubleRatchet(rootKey, opts, null);
    // The first DH ratchet in will use OUR signed-prekey secret against Alice's
    // ephemeral key. Represent that by seeding DHs' secret with the SPK secret
    // (a fresh public is derived for the outgoing header regardless).
    r.DHs = { publicKey: r.DHs.publicKey, secretKey: ourRatchetSecret };
    return r;
  }

  /** Canonical AEAD AD: the two identity X keys sorted (so both sides match). */
  private buildAd(): Uint8Array {
    const a = this.ourIdentityPub;
    const b = this.theirIdentityPub;
    // sort byte-wise so Alice and Bob build identical AD regardless of role
    const [first, second] = lexLt(a, b) ? [a, b] : [b, a];
    const ad = new Uint8Array(first.length + second.length);
    ad.set(first, 0);
    ad.set(second, first.length);
    return ad;
  }

  /** Encrypt plaintext -> { header, nonce, ciphertext } (all base64). */
  encrypt(plaintext: string): { header: RatchetHeader; nonce: string; ciphertext: string } {
    if (!this.sendingChain) {
      throw new Error('ratchet has no sending chain yet');
    }
    const chain = this.sendingChain;
    const { mk, nextCk } = kdfCk(chain.ck);
    chain.ck = nextCk;
    const n = chain.n++;
    // `pn` (previous-chain length) is fixed at DH-ratchet time and is *not*
    // incremented here; Signal sends the length of the last departed chain.
    const header: RatchetHeader = {
      dh: toBase64(this.DHs.publicKey),
      pn: this.pn,
      n,
    };
    const ad = this.adFor(header);
    const nonce = randomBytes(24);
    const ct = aeadEncrypt(
      mk,
      nonce,
      new TextEncoder().encode(plaintext),
      ad,
    );
    return {
      header,
      nonce: toBase64(nonce),
      ciphertext: toBase64(ct),
    };
  }

  /** Decrypt a received ratchet message. Handles out-of-order. Returns plaintext or null. */
  decrypt(header: RatchetHeader, nonceB64: string, ctB64: string): string | null {
    const theirDh = fromBase64(header.dh);
    const nonce = fromBase64(nonceB64);
    const ct = fromBase64(ctB64);

    // 1) New ratchet public key? Advance receiving chain.
    if (!this.DHr || toBase64(theirDh) !== toBase64(this.DHr)) {
      this.skipMessageKeys(header, this.receivingChain?.n ?? 0);
      this.performDhRatchet(theirDh);
    }

    // 2) Skip forward to reach header.n.
    if (this.receivingChain && header.n > this.receivingChain.n) {
      this.skipMessageKeys(header, header.n);
    }

    const chain = this.receivingChain;
    if (!chain) return null;

    let mk: Uint8Array | null = null;
    const skipKey = `${toBase64(this.DHr!)}_${header.n}`;
    if (chain.skipped.has(skipKey)) {
      mk = chain.skipped.get(skipKey)!;
      chain.skipped.delete(skipKey);
    } else if (header.n === chain.n) {
      // In-order message key.
      const d = kdfCk(chain.ck);
      chain.ck = d.nextCk;
      chain.n += 1;
      mk = d.mk;
    } else if (header.n < chain.n) {
      // Already consumed and not in skipped-dict -> duplicate/lost key.
      return null;
    } else {
      return null; // skipped too far / inconsistent
    }

    const ad = this.adFor(header);
    const plain = aeadDecrypt(mk, nonce, ct, ad);
    if (!plain) return null;
    try {
      return new TextDecoder().decode(plain);
    } catch {
      return null;
    }
  }

  /** Skip message keys up to (not including) `upToN` in the receiving chain. */
  private skipMessageKeys(header: RatchetHeader, upToN: number): void {
    const chain = this.receivingChain;
    if (!chain) return;
    if (upToN - chain.n > MAX_SKIP) {
      throw new Error('too many skipped messages (possible DoS)');
    }
    const theirDh = fromBase64(header.dh);
    while (chain.n < upToN) {
      const { mk, nextCk } = kdfCk(chain.ck);
      chain.skipped.set(`${toBase64(theirDh)}_${chain.n}`, mk);
      chain.ck = nextCk;
      chain.n += 1;
    }
  }

  /**
   * Perform a single DH ratchet step (AdvancedKeys): resets the receiving chain
   * from the new DHr, then derives a fresh sending chain from a new DH keypair.
   */
  private performDhRatchet(theirNewDh: Uint8Array): void {
    // receipt chain away from old DHr
    this.DHr = theirNewDh;
    const dec = kdfRk(this.rootKey, this.scalarmult(theirNewDh, this.DHs.secretKey));
    this.rootKey = dec.newRk;
    this.receivingChain = { ck: dec.ck, skipped: new Map(), n: 0 };

    // sending chain from a brand-new DH key pair
    const newDhs = generateKeyPair();
    const enc = kdfRk(this.rootKey, this.scalarmult(theirNewDh, newDhs.secretKey));
    this.rootKey = enc.newRk;
    if (this.sendingChain) this.pn = this.sendingChain.n;
    this.sendingChain = { ck: enc.ck, skipped: new Map(), n: 0 };
    this.DHs = newDhs;
  }

  /** AEAD associated data : AD || header-json. */
  private adFor(header: RatchetHeader): Uint8Array {
    const ad = this.buildAd();
    const h = new TextEncoder().encode(JSON.stringify(header));
    const out = new Uint8Array(ad.length + h.length);
    out.set(ad, 0);
    out.set(h, ad.length);
    return out;
  }

  private scalarmult(pub: Uint8Array, secret: Uint8Array): Uint8Array {
    return sodium().crypto_scalarmult(secret, pub);
  }
}