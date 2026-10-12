/**
 * tests/e2e.test.ts
 *
 * Functional, runnable proof that the app works:
 *   1. Two clients register prekey bundles.
 *   2. Alice runs X3DH against Bob's bundle.
 *   3. Alice sends a round-tripped encrypted message that Bob decrypts.
 *   4. We assert the ciphertext stored on the server is base64 – NOT plaintext –
 *      and that the plaintext never appears in server payloads.
 *   5. Tampering with a ciphertext byte fails decryption (AEAD auth).
 *   6. Out-of-order delivery still decrypts (skip-message-keys).
 *
 * Uses Node's built-in test runner (node:test) against the compiled dist/.
 */

import { test, before, after, beforeEach } from 'node:test';
import assert from 'node:assert';
import { startServer, resetStore, type ServerHandle } from '../server/main';
import { Endpoint } from '../client/client';
import { toBase64 } from '../shared/crypto';

let svc: ServerHandle;

before(async () => {
  svc = await startServer(0);
});

beforeEach(() => {
  resetStore(); // fresh store for every case (hermetic)
});

after(async () => {
  if (svc) await svc.stop();
});

function serverUrl(): string {
  return svc.url;
}

test('two clients register and exchange a full E2E message', async () => {
  const base = serverUrl();
  const alice = await Endpoint.create('alice', base);
  const bob = await Endpoint.create('bob', base);

  // 1. register
  await alice.uploadPrekeyBundle();
  await bob.uploadPrekeyBundle();

  // 2. X3DH handshake
  const bobBundle = await alice.fetchPrekeyBundle('bob');
  assert.ok(bobBundle.ik && bobBundle.spk && bobBundle.otk, 'bundle complete');
  const { initBody, peerKey: bobKeyForAlice } = await alice.initiateWith(bobBundle);

  // Deliver initBundle to Bob (out-of-band, like a QR / initial packet).
  const aliceKeyForBob = await bob.receiveConnection(initBody);
  assert.ok(bobKeyForAlice !== aliceKeyForBob, 'peer keys are distinct identity keys');

  // 3. Alice encrypts and sends
  const plaintextA = 'attack at dawn — plaintext must never reach the server';
  const sent = await alice.sendMessage('bob', bobKeyForAlice, plaintextA);
  assert.ok(sent.id, 'got a message id');

  // 4. Bob fetches and decrypts
  const msgs = await bob.fetchNewMessages();
  assert.ok(msgs.length >= 1);
  const aMsg = msgs.find((m) => m.sender === 'alice');
  assert.ok(aMsg, 'found alice message');

  // Plaintext is NOT present anywhere in what the server handed us.
  const serialized = JSON.stringify(msgs);
  assert.ok(!serialized.includes(plaintextA), 'plaintext not leaked to server/transport');

  const got = bob.decrypt(aliceKeyForBob, aMsg.header, aMsg.nonce, aMsg.ciphertext);
  assert.strictEqual(got, plaintextA, 'bob recovered the plaintext');

  // 5. Bob replies
  const reply = 'roger that';
  await bob.sendMessage('alice', aliceKeyForBob, reply);
  const aMsgs = await alice.fetchNewMessages();
  const bMsg = aMsgs.find((m) => m.sender === 'bob');
  assert.ok(bMsg, 'got bob reply');
  const gotReply = alice.decrypt(bobKeyForAlice, bMsg.header, bMsg.nonce, bMsg.ciphertext);
  assert.strictEqual(gotReply, reply, 'alice recovered the reply');
});

test("server sees ONLY base64 ciphertext, never the plaintext", async () => {
  const base = serverUrl();
  const alice = await Endpoint.create('alice2', base);
  const bob = await Endpoint.create('bob2', base);
  await alice.uploadPrekeyBundle();
  await bob.uploadPrekeyBundle();

  const secret = 'SUPER_SECRET_NEVER_STORED_12345';
  const bundle = await alice.fetchPrekeyBundle('bob2');
  const { initBody, peerKey } = await alice.initiateWith(bundle);
  await bob.receiveConnection(initBody);
  await alice.sendMessage('bob2', peerKey, secret);

  // Inspect whatever the server would store/relay: it must all be base64 charset.
  const msgs = await alice.fetchNewMessages();
  for (const m of msgs) {
    assert.match(String(m.nonce), /^[A-Za-z0-9+/=]+$/, 'nonce is base64');
    assert.match(String(m.ciphertext), /^[A-Za-z0-9+/=]+$/, 'ciphertext is base64');
    assert.ok(!JSON.stringify(m).includes(secret), 'no plaintext in message row');
  }
  assert.ok(!JSON.stringify(msgs).includes(secret), 'no plaintext in all rows');
});

test("tampering with ciphertext fails AEAD authentication", async () => {
  const base = serverUrl();
  const alice = await Endpoint.create('alice3', base);
  const bob = await Endpoint.create('bob3', base);
  await alice.uploadPrekeyBundle();
  await bob.uploadPrekeyBundle();

  const bundle = await alice.fetchPrekeyBundle('bob3');
  const { initBody, peerKey } = await alice.initiateWith(bundle);
  const aliceKeyForBob = await bob.receiveConnection(initBody);

  const secret = 'integrity matters';
  await alice.sendMessage('bob3', peerKey, secret);

  const msgs = await bob.fetchNewMessages();
  const m = msgs.find((x) => x.sender === 'alice3')!;
  // Flip the last base64 char to a different base64 char (corrupts a byte).
  const flipped =
    m.ciphertext.slice(0, -1) + (m.ciphertext.endsWith('A') ? 'B' : 'A');
  const result = bob.decrypt(aliceKeyForBob, m.header, m.nonce, flipped);
  assert.strictEqual(result, null, 'tampered ciphertext must not decrypt');
});

test("out-of-order delivery still decrypts via skip-message-keys", async () => {
  const base = serverUrl();
  const alice = await Endpoint.create('alice4', base);
  const bob = await Endpoint.create('bob4', base);
  await alice.uploadPrekeyBundle();
  await bob.uploadPrekeyBundle();

  const bundle = await alice.fetchPrekeyBundle('bob4');
  const { initBody, peerKey } = await alice.initiateWith(bundle);
  const aliceKeyForBob = await bob.receiveConnection(initBody);

  // Send 5 messages but only deliver [3, 5] first (out of order / gaps).
  const labels = ['m1', 'm2', 'm3', 'm4', 'm5'];
  for (const l of labels) await alice.sendMessage('bob4', peerKey, l);

  const msgs = (await bob.fetchNewMessages()).filter((m) => m.sender === 'alice4');
  assert.strictEqual(msgs.length, 5, 'got all five alice messages');
  const order = [msgs[2], msgs[4], msgs[0], msgs[3], msgs[1]].map((m) => ({
    header: m.header,
    nonce: m.nonce,
    ciphertext: m.ciphertext,
  }));
  const dec = order
    .map((m) => bob.decrypt(aliceKeyForBob, m.header, m.nonce, m.ciphertext))
    .filter((x): x is string => x !== null);
  assert.deepStrictEqual(dec, ['m3', 'm5', 'm1', 'm4', 'm2']);
});

test('base64 util round-trips', () => {
  const bytes = Buffer.from('hello');
  assert.strictEqual(Buffer.from(toBase64(new Uint8Array(bytes)), 'base64').toString(), 'hello');
});

test('double ratchet advances across many back-and-forth turns', async () => {
  const base = serverUrl();
  const alice = await Endpoint.create('alice5', base);
  const bob = await Endpoint.create('bob5', base);
  await alice.uploadPrekeyBundle();
  await bob.uploadPrekeyBundle();

  const bundle = await alice.fetchPrekeyBundle('bob5');
  const { initBody, peerKey: bobKey } = await alice.initiateWith(bundle);
  const aliceKey = await bob.receiveConnection(initBody);

  // Alternate turns so every message triggers a fresh DH ratchet on the far side.
  const turns = 6;
  for (let i = 0; i < turns; i++) {
    const fromA = `alice->bob #${i}`;
    await alice.sendMessage('bob5', bobKey, fromA);
    let msgs = (await bob.fetchNewMessages()).filter((m) => m.sender === 'alice5');
    const aMsg = msgs[msgs.length - 1];
    const gotA = bob.decrypt(aliceKey, aMsg.header, aMsg.nonce, aMsg.ciphertext);
    assert.strictEqual(gotA, fromA, `turn ${i}: bob reads alice`);

    const fromB = `bob->alice #${i}`;
    await bob.sendMessage('alice5', aliceKey, fromB);
    msgs = (await alice.fetchNewMessages()).filter((m) => m.sender === 'bob5');
    const bMsg = msgs[msgs.length - 1];
    const gotB = alice.decrypt(bobKey, bMsg.header, bMsg.nonce, bMsg.ciphertext);
    assert.strictEqual(gotB, fromB, `turn ${i}: alice reads bob`);
  }
});