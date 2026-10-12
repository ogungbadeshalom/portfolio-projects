/**
 * stats.js — daily session + focus-minute tracking in localStorage.
 *
 * All storage access is wrapped in try/catch so the app still works
 * in private browsing or when storage is disabled. A daily key keeps
 * today's rollup isolated from previous days.
 */

const DAY_KEY = (d) => `pomodoro:${d.toISOString().slice(0, 10)}`; // e.g. pomodoro:2026-09-12
const SHAPE = { sessions: 0, focusMinutes: 0 };

function storage() {
  return window.localStorage;
}

/** Read today's rollup, never throwing. */
function readDay(date = new Date()) {
  try {
    const raw = storage().getItem(DAY_KEY(date));
    if (!raw) return { ...SHAPE };
    const parsed = JSON.parse(raw);
    return {
      sessions: Number.isFinite(parsed.sessions) ? parsed.sessions : 0,
      focusMinutes: Number.isFinite(parsed.focusMinutes) ? parsed.focusMinutes : 0,
    };
  } catch {
    return { ...SHAPE };
  }
}

/** Persist today's rollup, silently ignoring storage failures. */
function writeDay(rollup) {
  try {
    storage().setItem(DAY_KEY(), JSON.stringify(rollup));
  } catch {
    /* ignore — storage unavailable (private mode, quota) */
  }
}

/**
 * Record one completed work focus session.
 * @param {number} minutes how many full minutes the session lasted
 * @returns {object} the updated rollup
 */
export function addSession(minutes) {
  const rollup = readDay();
  rollup.sessions += 1;
  rollup.focusMinutes += Math.max(1, Math.round(minutes));
  writeDay(rollup);
  return rollup;
}

/** Today's rollup: { sessions, focusMinutes }. */
export function getTodayStats() {
  return readDay();
}

export default { addSession, getTodayStats };