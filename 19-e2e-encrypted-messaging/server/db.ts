/**
 * server/db.ts
 *
 * In-memory storage where the server keeps ONLY opaque ciphertext + the routing
 * metadata the protocol needs (sender, recipient, timestamp, message id).
 *
 * The server never parses or transforms `header` / `nonce` / `ciphertext`: they
 * are stored as base64 strings verbatim and relayed as-is. None of those fields
 * are ever logged or cracked open. Message types come from the shared protocol
 * contract (shared/protocol.ts).
 */

import type { StoredMessage } from '../shared/protocol';

export { StoredMessage };

export interface KeyBundleRow {
  owner: string;
  ik: string;
  spk: string;
  spkSig: string;
  otks: Record<string, string>; // otkId -> public key (only workspace, not secret)
  publishedAt: number;
  /** the raw last-fetched bundle handed to one initiator. */
  lastIssuedOtk?: { id: string; otk: string };
}

let msgSeq = 0;
const messages: StoredMessage[] = [];
const bundles = new Map<string, KeyBundleRow>();

function now(): number {
  return Date.now();
}

export function saveMessage(m: Omit<StoredMessage, 'id' | 'timestamp'>): StoredMessage {
  const row: StoredMessage = {
    ...m,
    id: `m${++msgSeq}`,
    timestamp: now(),
  };
  messages.push(row);
  return row;
}

/** `since` filters by timestamp (inclusive); default = all. */
export function listMessages(recipient?: string, since?: number): StoredMessage[] {
  return messages.filter(
    (m) =>
      (!recipient || m.recipient === recipient) &&
      (since === undefined || m.timestamp >= since),
  );
}

export function getMessage(id: string): StoredMessage | undefined {
  return messages.find((m) => m.id === id);
}

export function putBundle(owner: string, b: KeyBundleRow): void {
  const prev = bundles.get(owner);
  bundles.set(owner, {
    ...b,
    otks: prev ? { ...prev.otks, ...b.otks } : b.otks,
  });
}

export function getBundle(owner: string): KeyBundleRow | undefined {
  return bundles.get(owner);
}

/**
 * Claim a one-time prekey for an initiator. Return the claimed (id, publicKey)
 * pair and remove it so it can never be re-issued.
 */
export function claimOtk(owner: string, otkId?: string): { id: string; otk: string } | null {
  const row = bundles.get(owner);
  if (!row) return null;
  if (otkId) {
    const otk = row.otks[otkId];
    if (!otk) return null;
    delete row.otks[otkId];
    return { id: otkId, otk };
  }
  const id = Object.keys(row.otks)[0];
  if (!id) return null;
  const otk = row.otks[id];
  delete row.otks[id];
  return { id, otk };
}

/** The server can only ever "see" base64 strings — never the underlying bytes. */
export function storeStats(): { count: number } {
  return { count: messages.length };
}

export function resetStore(): void {
  messages.length = 0;
  msgSeq = 0;
  bundles.clear();
}