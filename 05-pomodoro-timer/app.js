/**
 * app.js — the single App instance. Wires the DOM, keyboard shortcuts, and the
 * pure Timer together. Owns the render loop (a rAF-driven ring update) and the
 * interval that ticks the clock.
 *
 * This module is the only piece that creates mutable global state (the exported
 * App instance).
 */

import { Timer, TimerState } from './timer.js';
import { playBell, disposeAudio } from './audio.js';
import { requestPermission, showNotification } from './notify.js';
import { addSession, getTodayStats } from './stats.js';

// Dimensions of the SVG progress ring (r = 120).
const RING_R = 120;
const RING_C = 2 * Math.PI * RING_R; // ≈ 754px circumference

const SETTINGS_KEY = 'pomodoro:settings';
const THEME_KEY = 'pomodoro:theme';
const DEFAULT_SETTINGS = {
  durations: { work: 25, short: 5, long: 15 }, // minutes
  soundOn: true,
  notifyOn: true,
};
const MODE_ORDER = ['work', 'short', 'long'];

const $ = (sel) => document.querySelector(sel);

/** Clamp + round an input to an integer within [min, max], or null if invalid. */
function clampInt(value, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Math.min(max, Math.max(min, Math.round(n)));
}

/** Safely load persisted settings; fall back to defaults on any failure. */
function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return structuredClone(DEFAULT_SETTINGS);
    const parsed = JSON.parse(raw);
    return {
      durations: {
        work: clampInt(parsed.durations?.work, 1, 120) ?? DEFAULT_SETTINGS.durations.work,
        short: clampInt(parsed.durations?.short, 1, 60) ?? DEFAULT_SETTINGS.durations.short,
        long: clampInt(parsed.durations?.long, 1, 120) ?? DEFAULT_SETTINGS.durations.long,
      },
      soundOn: parsed.soundOn !== false,
      notifyOn: parsed.notifyOn === true,
    };
  } catch {
    return structuredClone(DEFAULT_SETTINGS);
  }
}

function saveSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    /* ignore — storage unavailable (private mode, quota) */
  }
}

function readTheme() {
  try {
    return localStorage.getItem(THEME_KEY) || 'dark';
  } catch {
    return 'dark';
  }
}

function writeTheme(theme) {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* ignore */
  }
}

class App {
  constructor() {
    this.settings = loadSettings();

    this.timer = new Timer({
      work: this.settings.durations.work * 60,
      short: this.settings.durations.short * 60,
      long: this.settings.durations.long * 60,
    });

    this.el = {
      ring: $('#ring-progress'),
      time: $('#time-display'),
      cycle: $('#cycle-display'),
      stateText: $('#state-text'),
      startPause: $('#start-pause'),
      reset: $('#reset'),
      settingsBtn: $('#settings'),
      statSessions: $('#stat-sessions'),
      statMinutes: $('#stat-minutes'),
      themeToggle: $('#theme-toggle'),
      modeTabs: [...document.querySelectorAll('.mode-tab')],
      modal: $('#settings-modal'),
      form: $('#settings-form'),
      closeSettings: $('#close-settings'),
      durWork: $('#dur-work'),
      durShort: $('#dur-short'),
      durLong: $('#dur-long'),
      soundToggle: $('#sound-toggle'),
      notifyToggle: $('#notify-toggle'),
      ringWrap: $('.timer-ring-wrap'),
    };

    // Bounded handler so it can be removed on unload.
    this.onKeyDown = (e) => this.handleKey(e);
    this.rafId = null;
    this.lastRingOffset = -1;
    this.tickId = null;

    // Store the callbacks for the modal's first-interaction permission ask.
    this._permissionListeners = [];

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => this.init(), { once: true });
    } else {
      this.init();
    }
  }

  init() {
    this.setupModeTabs();
    this.setupControls();
    this.setupSettings();
    this.setupTheme();
    this.attachKeyboard();
    this.renderModeLabels();
    this.renderAll();
    this.updateStats();

    // Request notification permission on the first secure gesture, so the
    // browser associates it with user intent.
    const onFirstGesture = () => {
      if (this.settings.notifyOn) requestPermission();
      this._permissionListeners.forEach((fn) => fn());
      this._permissionListeners = [];
    };
    ['click', 'keydown'].forEach((evt) => {
      document.addEventListener(evt, onFirstGesture, { once: true });
    });
  }

  /* ------------------------------------------------------------------
   * Rendering
   * ------------------------------------------------------------------ */

  /** Full render of time text, ring, labels, and button chrome. */
  renderAll() {
    const { timer, el } = this;

    el.time.textContent = timer.remainingLabel;
    el.time.setAttribute('datetime', `PT${timer.remaining}S`);
    el.cycle.textContent = `Cycle ${timer.cycle} / 4`;

    // Status line (also gently read by SRs via the live region on changes).
    let stateName = 'Ready';
    if (timer.isRunning) stateName = 'Running';
    else if (timer.isPaused) stateName = 'Paused';
    el.stateText.textContent = stateName;

    // Start/Pause button reflects current state.
    if (timer.isRunning) {
      el.startPause.textContent = 'Pause';
      el.startPause.setAttribute('aria-pressed', 'true');
      el.startPause.classList.remove('is-paused');
    } else {
      el.startPause.textContent = 'Start';
      el.startPause.setAttribute('aria-pressed', 'false');
      el.startPause.classList.add('is-paused');
    }

    // Body data-mode drives the mode tint via CSS.
    document.body.dataset.mode = timer.mode;

    // Mode tabs stay in sync (identity of active tab).
    this.activateModeTab(timer.mode);

    // Static ring render when idle/paused; rAF loop when running.
    this.syncRingLoop();
  }

  /**
   * Run (or stop) the rAF loop that keeps the SVG ring smooth. When not running
   * we render exactly once and leave the CSS transition to settle.
   */
  syncRingLoop() {
    if (this.timer.isRunning) {
      if (!this.rafId) {
        const loop = () => {
          this.applyRingOffset();
          if (this.timer.isRunning) this.rafId = requestAnimationFrame(loop);
          else this.rafId = null;
        };
        this.rafId = requestAnimationFrame(loop);
      }
    } else if (this.rafId) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
      this.applyRingOffset();
    }
  }

  applyRingOffset() {
    const offset = RING_C * (1 - this.timer.progress);
    if (offset !== this.lastRingOffset) {
      this.el.ring.style.strokeDashoffset = offset.toFixed(2);
      this.lastRingOffset = offset;
    }
  }

  updateStats() {
    const stats = getTodayStats();
    this.el.statSessions.textContent = String(stats.sessions);
    this.el.statMinutes.textContent = String(stats.focusMinutes);
  }

  /* ------------------------------------------------------------------
   * Controls
   * ------------------------------------------------------------------ */

  setupControls() {
    this.el.startPause.addEventListener('click', () => this.toggleRunning());
    this.el.reset.addEventListener('click', () => this.reset());
    this.el.settingsBtn.addEventListener('click', () => this.openSettings());
  }

  toggleRunning() {
    const { timer } = this;
    if (timer.isRunning) {
      timer.pause();
    } else {
      playBell(0); // unlock/resume the Web Audio context on this gesture
      timer.start();
    }
    this.syncClock();
    this.renderAll();
  }

  reset() {
    this.timer.reset();
    this.syncClock();
    this.renderAll();
    this.announce('Timer reset');
  }

  /* ------------------------------------------------------------------
   * Clock / interval
   * ------------------------------------------------------------------ */

  syncClock() {
    if (this.timer.isRunning) {
      if (!this.tickId) this.tickId = setInterval(() => this.tick(), 1000);
    } else if (this.tickId) {
      clearInterval(this.tickId);
      this.tickId = null;
    }
  }

  tick() {
    const done = this.timer.tick();
    this.renderAll();
    if (done) {
      this.onComplete();
    } else if (!this.timer.isRunning) {
      // Paused or reset mid-interval — stop ticking.
      this.syncClock();
      this.renderAll();
    }
  }

  /** A session just completed: advance the cycle, fire hooks, announce. */
  onComplete() {
    this.syncClock();

    let message;
    if (this.timer.mode === 'work') {
      addSession(this.timer.total / 60);
      this.updateStats();
      const next = this.timer.onWorkComplete();
      message =
        next === 'long'
          ? `Great work! Long break (${this.settings.durations.long} min) starts.`
          : `Great work! Short break (${this.settings.durations.short} min) starts.`;
    } else {
      this.timer.onBreakComplete();
      message = `Break over. Back to work (${this.settings.durations.work} min).`;
    }

    if (this.settings.soundOn) playBell(0.5);
    if (this.settings.notifyOn) showNotification('Pomodoro Timer', { body: message });

    // Restart the pulse animation.
    this.el.ringWrap.classList.remove('is-complete');
    void this.el.ringWrap.offsetWidth; // force reflow to restart animation
    this.el.ringWrap.classList.add('is-complete');

    this.renderAll();
    this.announce(message);
  }

  /* ------------------------------------------------------------------
   * Modes
   * ------------------------------------------------------------------ */

  setupModeTabs() {
    this.el.modeTabs.forEach((tab) => {
      tab.addEventListener('click', () => this.selectMode(tab.dataset.mode));
      tab.addEventListener('keydown', (e) => this.handleTabRoving(e, tab));
    });
  }

  selectMode(mode) {
    this.timer.switchMode(mode);
    this.syncClock();
    this.renderAll();
  }

  /** Keep aria-selected + roving tabindex correct. */
  activateModeTab(mode) {
    this.el.modeTabs.forEach((tab) => {
      const active = tab.dataset.mode === mode;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
  }

  /** Arrow-key roving between tabs (standard tablist behavior). */
  handleTabRoving(e, tab) {
    const dirs = { ArrowRight: 1, ArrowLeft: -1 };
    if (!(e.key in dirs)) return;
    e.preventDefault();
    const idx = MODE_ORDER.indexOf(tab.dataset.mode);
    const next = MODE_ORDER[(idx + dirs[e.key] + MODE_ORDER.length) % MODE_ORDER.length];
    const nextTab = this.el.modeTabs[MODE_ORDER.indexOf(next)];
    this.selectMode(next);
    nextTab.focus();
  }

  /** Keep the duration numbers shown on the tabs in sync with settings. */
  renderModeLabels() {
    this.el.modeTabs.forEach((tab) => {
      const span = tab.querySelector('.mode-duration');
      if (span) span.textContent = String(this.settings.durations[tab.dataset.mode]);
    });
  }

  /* ------------------------------------------------------------------
   * Keyboard shortcuts (document-level)
   * ------------------------------------------------------------------ */

  attachKeyboard() {
    document.addEventListener('keydown', this.onKeyDown);
  }

  handleKey(e) {
    // Don't hijack keys while typing in a field or when the modal is open.
    const tag = e.target.tagName;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return;
    if (!this.el.modal.hidden) return;

    if (e.code === 'Space' || e.key === ' ') {
      e.preventDefault();
      this.toggleRunning();
    } else if (this.isBareKey(e, 'r')) {
      this.reset();
    } else if (this.isBareKey(e, 'm')) {
      const idx = MODE_ORDER.indexOf(this.timer.mode);
      this.selectMode(MODE_ORDER[(idx + 1) % MODE_ORDER.length]);
    }
  }

  isBareKey(e, key) {
    const lower = e.key.toLowerCase();
    return lower === key && !e.metaKey && !e.ctrlKey && !e.altKey;
  }

  /* ------------------------------------------------------------------
   * Settings modal
   * ------------------------------------------------------------------ */

  setupSettings() {
    this.el.form.addEventListener('submit', (e) => {
      e.preventDefault();
      this.saveSettingsFromForm();
    });
    this.el.closeSettings.addEventListener('click', () => this.closeSettings());
    document.querySelectorAll('[data-close-modal]').forEach((el) => {
      el.addEventListener('click', () => this.closeSettings());
    });
    // Escape closes the modal (document-level, only when open).
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !this.el.modal.hidden) this.closeSettings();
    });
  }

  openSettings() {
    this.el.durWork.value = this.settings.durations.work;
    this.el.durShort.value = this.settings.durations.short;
    this.el.durLong.value = this.settings.durations.long;
    this.el.soundToggle.checked = this.settings.soundOn;
    this.el.notifyToggle.checked = this.settings.notifyOn;

    this.el.modal.hidden = false;
    this.el.modal.setAttribute('aria-hidden', 'false');
    this.el.durWork.focus();
  }

  closeSettings() {
    this.el.modal.hidden = true;
    this.el.modal.setAttribute('aria-hidden', 'true');
    this.el.settingsBtn.focus();
  }

  saveSettingsFromForm() {
    const work = clampInt(this.el.durWork.value, 1, 120);
    const short = clampInt(this.el.durShort.value, 1, 60);
    const long = clampInt(this.el.durLong.value, 1, 120);
    if (work == null || short == null || long == null) {
      this.announce('Please enter valid durations');
      return;
    }

    this.settings.durations = { work, short, long };
    this.settings.soundOn = this.el.soundToggle.checked;
    this.settings.notifyOn = this.el.notifyToggle.checked;
    saveSettings(this.settings);

    // Re-apply durations to the timer (seconds). Ring recalibrates if idle.
    this.timer.setDurations({
      work: work * 60,
      short: short * 60,
      long: long * 60,
    });

    if (this.settings.notifyOn) requestPermission();

    this.renderModeLabels();
    this.renderAll();
    this.closeSettings();
    this.announce('Settings saved');
  }

  /* ------------------------------------------------------------------
   * Theme
   * ------------------------------------------------------------------ */

  setupTheme() {
    this.applyTheme(readTheme());
    this.el.themeToggle.addEventListener('click', () => {
      const isLight = document.documentElement.dataset.theme === 'light';
      this.applyTheme(isLight ? 'dark' : 'light');
    });
  }

  applyTheme(theme) {
    const isLight = theme === 'light';
    document.documentElement.dataset.theme = isLight ? 'light' : 'dark';
    this.el.themeToggle.setAttribute('aria-pressed', String(isLight));
    this.el.themeToggle.setAttribute(
      'aria-label',
      isLight ? 'Switch to dark theme' : 'Switch to light theme'
    );
    writeTheme(theme);
  }

  /* ------------------------------------------------------------------
   * Accessibility + lifecycle
   * ------------------------------------------------------------------ */

  /** Politely announce a message to screen readers. */
  announce(message) {
    let node = document.getElementById('announcer');
    if (!node) {
      node = document.createElement('div');
      node.id = 'announcer';
      node.className = 'sr-only';
      node.setAttribute('aria-live', 'polite');
      node.setAttribute('aria-atomic', 'true');
      document.body.appendChild(node);
    }
    node.textContent = '';
    // Defer a beat so identical consecutive messages still announce.
    setTimeout(() => {
      node.textContent = message;
    }, 50);
  }

  /** Tear down timers, rAF, and listeners on page unload. */
  destroy() {
    document.removeEventListener('keydown', this.onKeyDown);
    if (this.tickId) clearInterval(this.tickId);
    if (this.rafId) cancelAnimationFrame(this.rafId);
    disposeAudio();
  }
}

// Single mutable App instance (module export gives it a stable home).
export const AppInstance = new App();

// Make it reachable for debugging/console.
window.__App = AppInstance;

// Clean up resources when the page unloads.
window.addEventListener('beforeunload', () => AppInstance.destroy());

export default AppInstance;