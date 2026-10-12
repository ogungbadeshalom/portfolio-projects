/**
 * timer.js — pure state-machine Timer class.
 *
 * The Timer keeps its own state (running/paused/idle) plus the remaining
 * seconds of the current session. It is deliberately "pure": it owns no DOM
 * and only mutates its internal fields. UI rendering is the App's job.
 *
 * State machine:
 *   idle  --start()--> running --tick(pause=true)--> paused
 *   running --tick(finshed)--> idle        (session completed)
 *   paused --start()--> running
 *   *(idle|running|paused) --reset()--> idle
 */

const defaultDurations = {
  work: 25 * 60,
  short: 5 * 60,
  long: 15 * 60,
};

/** Read-only view of the legal internal states. */
export const TimerState = Object.freeze({
  IDLE: 'idle',
  RUNNING: 'running',
  PAUSED: 'paused',
});

export class Timer {
  /**
   * @param {object} [options]
   * @param {number} [options.work]   work duration in seconds
   * @param {number} [options.short]  short break duration in seconds
   * @param {number} [options.long]   long break duration in seconds
   */
  constructor(options = {}) {
    this.durations = {
      work: options.work ?? defaultDurations.work,
      short: options.short ?? defaultDurations.short,
      long: options.long ?? defaultDurations.long,
    };

    /** Current mode: 'work' | 'short' | 'long'. */
    this.mode = 'work';
    /** Remaining seconds in the current session. */
    this.remaining = this.durations.work;
    /** Total seconds the session started at (for the ring math). */
    this.total = this.durations.work;
    this.state = TimerState.IDLE;
    /** Cycle number within the current 4-cycle round (1-based). */
    this.cycle = 1;
    /** How many completed work sessions happened since the round reset. */
    this.roundWorkCount = 0;
  }

  /** Alias matching the spec's tick() naming while staying readable. */
  get durationsSec() {
    return this.durations;
  }

  /**
   * Configure durations (from settings). Applies current-mode total when the
   * timer is idle or paused, so the ring stays consistent.
   */
  setDurations({ work, short, long }) {
    if (!Number.isFinite(work) || !Number.isFinite(short) || !Number.isFinite(long)) {
      throw new TypeError('Durations must be finite numbers (seconds).');
    }
    this.durations = {
      work: Math.max(1, Math.round(work)),
      short: Math.max(1, Math.round(short)),
      long: Math.max(1, Math.round(long)),
    };

    if (this.state !== TimerState.RUNNING) {
      this.total = this.durations[this.mode];
      this.remaining = Math.min(this.remaining, this.total);
    }
  }

  start() {
    if (this.state === TimerState.RUNNING) return this.state;
    if (this.remaining <= 0) this.reset();
    this.state = TimerState.RUNNING;
    return this.state;
  }

  pause() {
    if (this.state !== TimerState.RUNNING) return this.state;
    this.state = TimerState.PAUSED;
    return this.state;
  }

  /** Pause-if-running, or reset to idle at full duration. */
  reset() {
    this.state = TimerState.IDLE;
    this.remaining = this.durations[this.mode];
    this.total = this.durations[this.mode];
    return this.state;
  }

  /**
   * Advance the clock by one second.
   * @returns {true} if the session completed (remaining hit 0), else {false}.
   */
  tick() {
    if (this.state !== TimerState.RUNNING) return false;
    this.remaining = Math.max(0, this.remaining - 1);
    if (this.remaining === 0) {
      this.state = TimerState.IDLE;
      return true;
    }
    return false;
  }

  /** Switch mode (work/short/long), resetting the session clock. */
  switchMode(mode) {
    if (!(mode in this.durations)) {
      throw new RangeError(`Unknown mode: ${mode}`);
    }
    this.mode = mode;
    this.state = TimerState.IDLE;
    this.total = this.durations[mode];
    this.remaining = this.total;
    return this.mode;
  }

  /**
   * Record a completed work session and advance the cycle.
   * Work completion -> next cycle. After 4 work sessions -> long break.
   * Called by App when a 'work' session finishes.
   */
  onWorkComplete() {
    this.roundWorkCount += 1;
    if (this.roundWorkCount >= 4) {
      this.cycle = 1;
      this.roundWorkCount = 0;
      this.switchMode('long');
    } else {
      this.cycle += 1;
      this.switchMode('short');
    }
    return this.mode;
  }

  /** A break finished -> return to work at the same cycle. */
  onBreakComplete() {
    this.switchMode('work');
    return this.mode;
  }

  /** 0..1 fraction remaining, used to drive the SVG ring offset. */
  get progress() {
    return this.total > 0 ? this.remaining / this.total : 0;
  }

  /** Human-readable mm:ss for the current remaining time. */
  get remainingLabel() {
    const m = Math.floor(this.remaining / 60);
    const s = this.remaining % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  get isRunning() {
    return this.state === TimerState.RUNNING;
  }

  get isPaused() {
    return this.state === TimerState.PAUSED;
  }

  get isIdle() {
    return this.state === TimerState.IDLE;
  }
}

export default Timer;