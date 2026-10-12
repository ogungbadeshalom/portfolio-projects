# Pomodoro Timer — Browser App

## Project Title
Pomodoro Timer (HTML/CSS/JS)

## Goal
A beautiful, minimal Pomodoro timer that runs in the browser. 25 min work, 5 min break, 4 cycles = long break. Sound notification when timer ends. Track sessions in localStorage.

## Why this project
DOM manipulation, browser APIs (timer, audio, storage), keyboard shortcuts, accessibility. Frontend fundamentals.

## What You Build

A single `index.html` file (plus optional CSS/JS split) with:

- Big circular timer display (SVG progress ring)
- Start / Pause / Reset buttons
- Mode switcher: Work (25) / Short Break (5) / Long Break (15)
- Cycle counter (1/4, 2/4, etc.)
- Sound notification when timer ends
- Browser notification (Notification API)
- Keyboard shortcuts: Space=start/pause, R=reset, M=mode
- Stats: today's completed sessions, total minutes focused (localStorage)
- Settings panel (custom durations, sound on/off)

## Tech
- **Vanilla HTML + CSS + JavaScript** (no frameworks)
- **CSS custom properties** for theming
- **SVG** for the circular progress ring
- **Web Audio API** for sound (or simple `<audio>` tag)
- **Notification API** for browser notifications
- **localStorage** for persistence
- **Service Worker** (stretch goal for offline support)

## Architecture

```
pomodoro/
├── index.html              # main page
├── styles.css              # all styles
├── app.js                  # main logic
├── timer.js                # Timer class (start/pause/reset/tick)
├── stats.js                # localStorage stats manager
├── audio.js                # sound playback
├── notify.js               # browser notifications
├── test.html               # manual test page
├── package.json            # for dev server (optional, just for `npx serve`)
└── CLAUDE.md
```

## Build Order

1. **`index.html`** — skeleton with timer display, buttons, mode tabs
2. **`styles.css`** — dark theme, large center-aligned timer, circular SVG ring
3. **`timer.js`** — `Timer` class with `start()`, `pause()`, `reset()`, `tick()` (1s interval), state machine
4. **`app.js`** — wire up buttons + keyboard shortcuts to Timer methods
5. **`audio.js`** — play bell sound when timer reaches 0 (use `<audio>` with data URI or short MP3)
6. **`notify.js`** — request Notification permission, fire on timer end
7. **`stats.js`** — track today's sessions, total minutes, persist to localStorage
8. **Settings panel** — modal with duration inputs, save to localStorage

## Requirements

- No external dependencies (no React, no Vue, no jQuery)
- Works offline once loaded (no CDN dependencies at runtime)
- Keyboard shortcuts work without focus on button (document-level listeners)
- Accessible: ARIA labels, focus visible, screen reader announces state changes
- Responsive: works on phone (320px) and desktop (1920px)
- Theme: dark mode by default, with light mode toggle

## Code Standards

- Use ES modules (`type="module"`) for organization
- No global state except a single `App` instance
- Timer class is pure: `tick()` returns new state, doesn't mutate
- localStorage operations wrapped in try/catch (private browsing fails)
- Use `requestAnimationFrame` for smooth SVG ring updates
- All event listeners cleaned up on page unload (memory leaks)

## Verification

```bash
# Open in browser
xdg-open index.html

# Test in different browsers
firefox index.html
chromium index.html

# Manual test checklist:
# - Timer counts down accurately
# - Pause/Resume works
# - Mode switch changes color + duration
# - 4th cycle triggers long break (15 min)
# - Sound plays at 0
# - Browser notification appears
# - localStorage persists stats across refresh
```

## Stretch Goals

- Task list integration (assign a task to each pomodoro)
- Statistics page with charts (Chart.js via CDN)
- Sync stats to cloud (Google Sheets API)
- PWA with offline support + install prompt
- Custom sound upload
- Theme switcher (multiple themes)
- Animation when timer completes (CSS keyframes)

## What You'll Learn

- Browser timer API (setInterval, requestAnimationFrame)
- SVG manipulation for progress rings
- localStorage patterns
- Web Audio API basics
- Notification API
- ARIA accessibility patterns
- Pure CSS animations

## Time Estimate
3-4 hours for clean version. 6-8 hours with settings + stats + accessibility.