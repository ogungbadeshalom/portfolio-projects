/**
 * audio.js — end-of-timer bell using the Web Audio API.
 *
 * No external audio assets needed: a short chord is synthesized on demand.
 * The AudioContext must be (re)created/resumed after a user gesture, which is
 * why resume() is called from App on the first Start click.
 */

let ctx = null;

/** Lazily create and unlock the Web Audio context. */
function ensureContext() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null; // unsupported browser
    ctx = new AC();
  }
  // Resume after autoplay policy — safe to call repeatedly.
  if (ctx.state === 'suspended') ctx.resume();
  return ctx;
}

/**
 * Play a pleasant two-note "ding".
 * @param {number} [volume] 0..1
 */
export function playBell(volume = 0.5) {
  const ac = ensureContext();
  if (!ac) return;

  const master = ac.createGain();
  master.gain.value = Math.min(1, Math.max(0, volume));
  master.connect(ac.destination);

  const now = ac.currentTime;
  // 'E6' then 'A6' — a rising perfect fourth, ~0.9s warm bell.
  [[1318.51, 0], [1760.0, 0.16]].forEach(([freq, at]) => {
    const osc = ac.createOscillator();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, now + at);

    const gain = ac.createGain();
    gain.gain.setValueAtTime(0.0001, now + at);
    gain.gain.exponentialRampToValueAtTime(0.5, now + at + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + at + 0.9);

    osc.connect(gain);
    gain.connect(master);
    osc.start(now + at);
    osc.stop(now + at + 0.95);
  });
}

/** Release the AudioContext (called on unload). */
export function disposeAudio() {
  if (ctx) {
    ctx.close().catch(() => {});
    ctx = null;
  }
}

export default { playBell, disposeAudio };