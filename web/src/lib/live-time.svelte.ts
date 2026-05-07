// Process-wide ticking clock for components that render relative
// timestamps ("3s ago", "5m ago", …).
//
// Why a shared tick instead of one timer per ChatMessage:
//   The chat surface can have 100+ messages on screen during a
//   long session. A `setInterval` per row would mean 100 timer
//   callbacks per tick, all racing the same Svelte effect graph
//   for what is ultimately a single piece of derived state ("what
//   time is it now?"). Hoisting the tick to a single module-level
//   `$state` rune means N message components all subscribe to one
//   reactive value, and Svelte 5 dedups the rerender pass.
//
// Why 5 seconds:
//   The "Ns ago" bucket is the only one where finer granularity is
//   visible to the player; once we cross into "Nm ago" the bucket
//   size is 60s and a 5s tick is invisible. 5s gives the feed a
//   live feel without burning a wakeup every second across a quiet
//   tab. (Most users will leave the page idle while reading, and a
//   1s tick across every persisted message would show up in
//   battery profilers.)
//
// SSR / test guards: we only start the interval in a real browser.
// Under jsdom or node tests, the timer never starts and the rune
// stays at its initial value, which is what the timestamp formatter
// expects (no flicker, deterministic output).

const TICK_INTERVAL_MS = 5_000;

let tickHandle: ReturnType<typeof setInterval> | null = null;

// Plain $state rune at module scope. The .svelte.ts extension lets
// Svelte's compiler treat this file as a runes module so external
// components can read `liveTime.now` reactively.
const liveTime = $state({ now: Date.now() });

function startTickingIfNeeded(): void {
  if (tickHandle !== null) return;
  if (typeof window === "undefined") return;
  tickHandle = setInterval(() => {
    liveTime.now = Date.now();
  }, TICK_INTERVAL_MS);
  // Refresh on tab regain: while the tab was hidden, the interval
  // may have been throttled by the browser, so the first paint
  // after returning would otherwise show a stale "X minutes ago".
  // We poke `now` immediately on visibilitychange to anchor the
  // freshly-visible feed to real wall-clock time before the next
  // interval fires.
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        liveTime.now = Date.now();
      }
    });
  }
}

startTickingIfNeeded();

export { liveTime };
