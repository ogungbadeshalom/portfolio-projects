/**
 * notify.js — browser Notification API wrapper.
 *
 * Requests permission lazily (usually triggered by a user gesture) and fires a
 * native notification when a session completes. Falls back silently when
 * unsupported or denied.
 */

/**
 * Ask the user for notification permission.
 * @returns {Promise<boolean>} true if permission is granted.
 */
export async function requestPermission() {
  if (!('Notification' in window)) return false;
  if (Notification.permission === 'default') {
    try {
      await Notification.requestPermission();
    } catch {
      return false;
    }
  }
  return Notification.permission === 'granted';
}

/**
 * Show a notification.
 * @param {string} title
 * @param {object} [options] Notification options (body, tag, ...).
 */
export function showNotification(title, options = {}) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  try {
    // Reuse a tag so repeated notifications replace each other.
    const n = new Notification(title, { tag: 'pomodoro-timer', icon: '', ...options });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    /* ignore — best effort */
  }
}

/** Whether the user has granted permission (for the settings checkbox). */
export function isPermissionGranted() {
  return 'Notification' in window && Notification.permission === 'granted';
}

export default { requestPermission, showNotification, isPermissionGranted };