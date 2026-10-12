# Pomodoro Timer

A beautiful, minimal Pomodoro timer that runs entirely in the browser — no build step, no dependencies, no CDN at runtime.

## How to open

Just open `index.html` in any modern browser (double-click it, or drag it into a browser window). Everything is static HTML/CSS/JS and works offline.

> Tip: opening via `file://` works fine. If the browser notification permission or Web Audio behaves oddly in your environment, serving the folder with `npx serve` also works.

## Features

- **Working pomodoro loop** — 25 min work, 5 min short break, 15 min long break, 4 work sessions per round.
- **Circular SVG progress ring** — smooth `requestAnimationFrame`-driven countdown.
- **Controls** — Start / Pause / Reset.
- **Mode switcher** — Work / Short Break / Long Break with a roving-tabindex tablist (arrow-key navigation works too).
- **Cycle counter** — shows which of the 4 sessions you're on.
- **End-of-timer sound** — a synthesized two-note bell via the Web Audio API (no audio files needed).
- **Browser notifications** — optional, permission requested on first interaction.
- **Keyboard shortcuts** (document-level, work without focusing a control):
  - `Space` — start / pause
  - `R` — reset
  - `M` — switch mode
- **Stats** — today's completed sessions and total focus minutes, persisted in `localStorage`.
- **Settings panel** — custom durations, sound on/off, and notification on/off, persisted locally.
- **Theming** — dark theme by default with a light-mode toggle (runs through CSS custom properties).
- **Responsive** — works from 320px phones up to 1920px desktops.
- **Accessible** — ARIA labels, visible focus rings, screen-reader state announcements, reduced-motion support.

## Project structure

```
├── index.html    # markup: ring, controls, mode tabs, settings modal
├── styles.css    # theming (custom properties) + responsive layout
├── app.js        # the single App instance: wires UI + keyboard to Timer
├── timer.js      # pure state-machine Timer class (start/pause/reset/tick)
├── stats.js      # daily session + focus-minute tracking (localStorage, try/catch)
├── audio.js      # Web Audio bell
├── notify.js     # Notification API wrapper
└── test.html     # manual test checklist
```

## Keyboard shortcuts

| Key            | Action              |
| -------------- | ------------------- |
| `Space`        | Start / Pause       |
| `R`            | Reset               |
| `M`            | Switch mode         |
| `ArrowLeft/Right` | Move between modes (when a mode tab is focused) |

## Build / run

No build step. This is intentionally dependency-free vanilla ES modules.

## Notes

- All `localStorage` access is wrapped in `try/catch`, so the app still runs in private-browsing mode.
- Listeners and timers are cleaned up on `beforeunload`.