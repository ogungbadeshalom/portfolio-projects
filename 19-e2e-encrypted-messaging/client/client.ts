/**
 * client/client.ts
 *
 * The client-side of the E2E protocol, network-equivalent to what the CLAUDE.md
 * calls "client/ui.ts + client/messages.ts + client/session.ts". In a real Vite
 * + React app these would be driven from the UI; here they're driven from a
 * small CLI so the SAME protocol can be exercised end-to-end and tested.
 *
 * Flow:
 *   1. uploadPrekeyBundle()        -> POST /api/keys/upload
 *   2. fetchPrekeyBundle(peer)     -> GET  /api/keys/{peer} (claims one OTK)
 *   3. session.initiate(bundle)    -> X3DH (initiator)
 *   4. send encrypted message      -> POST /api/messages (server stores ciphertext)
 *   5. recipient receives init + msg, session.receiveInit(...) + ratchet decrypt
 */

import { UserSession } from '../shared/session';
import type { InitBundleWire, PrekeyBundleWire } from '../shared/session';
import { toBase64, type RatchetHeader } from '../shared/crypto';
import WebSocket from 'ws';

export class Endpoint {
  readonly user: UserSession;
  readonly serverUrl: string;
  private ws: WebSocket | null = null;
  onNotice: ((n: { sender: string; recipient: string }) => void) | null = null;

  private constructor(user: UserSession, serverUrl: string) {
    this.user = user;
    this.serverUrl = serverUrl.replace(/\/+$/, '');
  }

  static async create(name: string, serverUrl: string): Promise<Endpoint> {
    const user = await UserSession.create(name);
    return new Endpoint(user, serverUrl);
  }

  // ------------------------------------------------------- HTTP helpers
  private async request(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<{ status: number; json: any }> {
    const res = await fetch(this.serverUrl + path, {
      method,
      headers: { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let json: any = null;
    try {
      json = await res.json();
    } catch {
      /* no body */
    }
    return { status: res.status, json };
  }

  // ------------------------------------------------------- register
  async uploadPrekeyBundle(): Promise<void> {
    // Publish 10 fresh one-time prekeys.
    const otks: Record<string, string> = {};
    for (const [id, kp] of this.user.record.oneTimePreKeys) {
      otks[id] = toBase64(kp.publicKey);
    }
    const bundle = this.user.makeBundle('owner');
    const r = await this.request('POST', '/api/keys/upload', {
      identityKey: this.user.name,
      ik: bundle.ik,
      spk: bundle.spk,
      spkSig: bundle.spkSig,
      otks,
    });
    if (r.status !== 200) throw new Error(`uploadPrekeyBundle failed: ${r.status}`);
  }

  async fetchPrekeyBundle(peerName: string): Promise<PrekeyBundleWire> {
    const r = await this.request('GET', `/api/keys/${encodeURIComponent(peerName)}`);
    if (r.status !== 200) throw new Error(`fetchPrekeyBundle(${peerName}) failed: ${r.status}`);
    return r.json as PrekeyBundleWire;
  }

  // ------------------------------------------------------- session
  /** X3DH initiator: start a session with a peer's prekey bundle. */
  async initiateWith(peerBundle: PrekeyBundleWire): Promise<{ initBody: string; peerKey: string }> {
    return this.user.initiate(peerBundle);
  }

  /** X3DH responder: accept an init bundle (as the message sender's peer). */
  async receiveConnection(initBody: string): Promise<string> {
    const init = JSON.parse(initBody) as InitBundleWire;
    return this.user.receiveInit(init);
  }

  // ------------------------------------------------------- messaging
  async sendMessage(
    peerUser: string,
    peerKey: string,
    plaintext: string,
  ): Promise<{ id: string; timestamp: number }> {
    const msg = this.user.send(peerKey, plaintext);
    const r = await this.request('POST', '/api/messages', {
      sender: this.user.name,
      recipient: peerUser,
      header: JSON.stringify(msg.header), // header object -> opaque JSON string
      nonce: msg.nonce,
      ciphertext: msg.ciphertext,
    });
    if (r.status !== 201) throw new Error(`sendMessage failed: ${r.status}`);
    return r.json;
  }

  async fetchNewMessages(since?: number): Promise<
    Array<{ sender: string; header: RatchetHeader; nonce: string; ciphertext: string }>
  > {
    const q = since !== undefined ? `?since=${since}` : '';
    const r = await this.request('GET', `/api/messages${q}`);
    const rows = (r.json ?? []) as Array<{
      sender: string;
      header: string;
      nonce: string;
      ciphertext: string;
    }>;
    return rows.map((m) => ({
      sender: m.sender,
      header: JSON.parse(m.header) as RatchetHeader,
      nonce: m.nonce,
      ciphertext: m.ciphertext,
    }));
  }

  /** Decrypt a fetched message addressed to us with the correct peer session. */
  decrypt(peerKey: string, header: RatchetHeader, nonce: string, ciphertext: string): string | null {
    return this.user.decrypt(peerKey, header, nonce, ciphertext);
  }

  // ------------------------------------------------------- win
  async connectWS(): Promise<void> {
    const url = `${this.serverUrl.replace(/^http/, 'ws')}/ws?user=${encodeURIComponent(this.user.name)}`;
    const ws = new WebSocket(url);
    this.ws = ws;
    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = (e) => reject(e instanceof Error ? e : new Error(String(e)));
    });
    ws.onmessage = (ev) => {
      const data = typeof ev.data === 'string' ? ev.data : ev.data.toString();
      try {
        const n = JSON.parse(data);
        if (n?.kind === 'message' && this.onNotice) this.onNotice(n);
      } catch {
        /* ignore */
      }
    };
  }
}