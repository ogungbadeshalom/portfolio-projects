/**
 * server/main.ts
 *
 * Untrusted relay server. Runs HTTP endpoints for prekey bundles + ciphertext
 * delivery and a WebSocket relay for real-time "you have a message" notices.
 *
 * It stores ONLY:
 *   - identity & prekey public material (ik, spk, spkSig, otks) needed to run X3DH
 *   - opaque ciphertext + routes + timestamps
 *
 * It NEVER sees plaintext. All ciphertext is stored as base64 strings and
 * relayed verbatim. No logging of ciphertext. See verify step in README.
 */

import * as http from 'http';
import WebSocket from 'ws';
import {
  saveMessage,
  listMessages,
  getBundle,
  putBundle,
  claimOtk,
  resetStore,
  type KeyBundleRow,
} from './db';

export interface ServerHandle {
  server: http.Server;
  wss: WebSocket.Server;
  port: number;
  url: string;
  stop: () => Promise<void>;
}

interface WsByUser {
  [username: string]: WebSocket;
}

const clients: WsByUser = {};

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => {
      data += c;
    });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

function sendJson(res: http.ServerResponse, code: number, obj: unknown): void {
  res.writeHead(code, { 'content-type': 'application/json' });
  res.end(JSON.stringify(obj));
}

function jsonBody<T>(req: http.IncomingMessage): Promise<T> {
  return readBody(req).then((s) => {
    try {
      return JSON.parse(s) as T;
    } catch {
      throw new Error('invalid json');
    }
  });
}

function handleRoute(
  req: http.IncomingMessage,
  res: http.ServerResponse,
  path: string,
): boolean | Promise<boolean> {
  // ---- /api/keys/upload  (PUT bundle)
  if (req.method === 'POST' && path === '/api/keys/upload') {
    return jsonBody<any>(req).then((b) => {
      const owner = b?.identityKey;
      if (!owner || typeof owner !== 'string') return sendJson(res, 400, { error: 'identityKey required' }) as unknown as boolean;
      const row: KeyBundleRow = {
        owner,
        ik: String(b.ik),
        spk: String(b.spk),
        spkSig: String(b.spkSig),
        otks: (b.otks ?? {}) as Record<string, string>,
        publishedAt: Date.now(),
      };
      putBundle(owner, row);
      sendJson(res, 200, { ok: true, owner });
      return true;
    });
  }

  // ---- GET /api/keys/{user}
  const claimMatch = path.match(/^\/api\/keys\/([^/]+)\/prekey$/);
  if (claimMatch) {
    if (req.method !== 'POST') return false;
    const owner = decodeURIComponent(claimMatch[1]);
    const row = getBundle(owner);
    if (!row) return sendJson(res, 404, { error: 'no bundle' }) as unknown as boolean;
    const claimed = claimOtk(owner);
    sendJson(res, 200, {
      identityKey: owner,
      ik: row.ik,
      spk: row.spk,
      spkSig: row.spkSig,
      otkId: claimed ? claimed.id : null,
      otk: claimed ? claimed.otk : null,
    });
    return true;
  }

  const keysMatch = path.match(/^\/api\/keys\/([^/]+)$/);
  if (keysMatch) {
    if (req.method !== 'GET') return false;
    const owner = decodeURIComponent(keysMatch[1]);
    const row = getBundle(owner);
    if (!row) return sendJson(res, 404, { error: 'no bundle' }) as unknown as boolean;
    const claimed = claimOtk(owner); // consume one OTK for this initiator
    sendJson(res, 200, {
      identityKey: owner,
      ik: row.ik,
      spk: row.spk,
      spkSig: row.spkSig,
      otkId: claimed ? claimed.id : null,
      otk: claimed ? claimed.otk : null,
    });
    return true;
  }

  // ---- POST /api/messages   (send ciphertext)
  if (req.method === 'POST' && path === '/api/messages') {
    return jsonBody<any>(req).then((b) => {
      if (!b?.sender || !b?.recipient || !b?.header || !b?.nonce || !b?.ciphertext) {
        return sendJson(res, 400, { error: 'missing fields (sender, recipient, header, nonce, ciphertext)' }) as unknown as boolean;
      }
      const saved = saveMessage({
        sender: String(b.sender),
        recipient: String(b.recipient),
        header: String(b.header),
        nonce: String(b.nonce),
        ciphertext: String(b.ciphertext),
      });
      const peer = clients[b.recipient];
      if (peer && peer.readyState === WebSocket.OPEN) {
        peer.send(
          JSON.stringify({
            kind: 'message',
            sender: saved.sender,
            recipient: saved.recipient,
            timestamp: saved.timestamp,
          }),
        );
      }
      sendJson(res, 201, { id: saved.id, timestamp: saved.timestamp });
      return true;
    });
  }

  // ---- GET /api/messages?recipient=&since=
  if (req.method === 'GET' && path.startsWith('/api/messages')) {
    const u = new URL(req.url!, 'http://x');
    const recipient = u.searchParams.get('recipient') ?? undefined;
    const since = u.searchParams.get('since') ? Number(u.searchParams.get('since')) : undefined;
    const rows = listMessages(recipient, since);
    sendJson(res, 200, rows.map((m) => ({
      id: m.id,
      sender: m.sender,
      recipient: m.recipient,
      timestamp: m.timestamp,
      header: m.header,
      nonce: m.nonce,
      ciphertext: m.ciphertext,
    })));
    return true;
  }

  return false;
}

export async function startServer(port = 0): Promise<ServerHandle> {
  const server = http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url!, 'http://x');
      const handled = await handleRoute(req, res, url.pathname);
      if (!handled) sendJson(res, 404, { error: 'not found' });
    } catch (e) {
      sendJson(res, 500, { error: String(e) });
    }
  });

  const wss = new WebSocket.Server({ noServer: true });
  const wsUser = new Map<WebSocket, string>();
  server.on('upgrade', (req, socket, head) => {
    const url = new URL(req.url!, 'http://x');
    const name = url.searchParams.get('user');
    if (!name) {
      socket.destroy();
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws) => {
      wsUser.set(ws, name);
      wss.emit('connection', ws, req);
    });
  });
  wss.on('connection', (ws, req) => {
    void req;
    const user = wsUser.get(ws) ?? '';
    if (!user) return;
    clients[user] = ws;
    ws.on('close', () => {
      if (clients[user] === ws) delete clients[user];
      wsUser.delete(ws);
    });
  });

  await new Promise<void>((resolve) => server.listen(port, resolve));
  const addr = server.address();
  const actualPort = typeof addr === 'object' && addr ? addr.port : port;
  return {
    server,
    wss,
    port: actualPort,
    url: `http://127.0.0.1:${actualPort}`,
    stop: async () => {
      for (const c of Object.values(clients)) {
        try {
          c.close();
        } catch {
          /* ignore */
        }
      }
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  };
}

/** Used by tests to clear state between cases. */
export { resetStore };

// Direct execution: `node dist/server/main.js` (or `npm run start:server`)
if (require.main === module) {
  startServer(Number(process.env.PORT) || 8080).then((h) => {
    // eslint-disable-next-line no-console
    console.log(`echat relay listening on ${h.url}`);
  });
}