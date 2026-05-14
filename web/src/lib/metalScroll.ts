/*
 * `metalScroll` — Svelte action that replaces the native scrollbar
 * on a scrollable element with a fully-bespoke metallic gold thumb +
 * track overlay.
 *
 * Why this is JS-driven instead of CSS-only:
 *   macOS Chrome/Safari draw overlay scrollbars at the OS level when
 *   the user has "Show scroll bars: When scrolling" or "Automatically
 *   based on mouse or trackpad" set in System Settings → Appearance.
 *   In those modes the `::-webkit-scrollbar` pseudo-elements either
 *   render as the OS overlay shape (rounded, auto-hiding) or get
 *   ignored entirely — there is no CSS property that opts out at the
 *   author level. The only reliable workaround is to hide the native
 *   scrollbar completely (`scrollbar-width: none` + `::-webkit-
 *   scrollbar { display: none }`) and paint our own with JS, which is
 *   what this action does.
 *
 * Usage:
 *   <div use:metalScroll style="overflow-y: auto; position: relative;">
 *     ...content...
 *   </div>
 *
 * Implementation strategy:
 *   We do NOT wrap the viewport (which would break flex/grid parents).
 *   Instead, we ensure the viewport itself has `position: relative` and
 *   append the track + thumb as the viewport's last child, then set
 *   `position: sticky; top: 0; right: 0` on the track so it floats
 *   over the scrolled content while staying anchored to the viewport
 *   edge. The thumb is positioned absolute inside the track.
 *
 *   We need to set the viewport's `position: relative` because sticky
 *   relies on the scroll container being the containing block — and
 *   for the track to sit at the right edge regardless of content width
 *   we use the trick of `float: right` + `clear: right` so the track
 *   occupies space at the right edge of each line. Then `position:
 *   sticky` keeps it pinned at top during scroll.
 *
 *   Actually simpler: append a sibling track via `position: absolute`
 *   inside the *parent* of the viewport, sized to match the viewport's
 *   bounding rect. We update the size on resize. This keeps the
 *   viewport's children untouched.
 */

export interface MetalScrollOptions {
  width?: number;
  minThumb?: number;
}

interface MetalScrollState {
  viewport: HTMLElement;
  track: HTMLDivElement;
  thumb: HTMLDivElement;
  resizeObserver: ResizeObserver;
  mutationObserver: MutationObserver;
  width: number;
  minThumb: number;
  dragging: boolean;
  dragStartY: number;
  dragStartScrollTop: number;
}

/* Inject the scoped stylesheet once per document. The styles are
 * inline rather than in a Svelte component because the action needs
 * to work on arbitrary elements without requiring callers to import
 * a stylesheet. */
function ensureStylesInjected(): void {
  if (typeof document === "undefined") return;
  if (document.getElementById("metal-scroll-styles") !== null) return;
  const style = document.createElement("style");
  style.id = "metal-scroll-styles";
  style.textContent = `
    .metal-scroll-host {
      scrollbar-width: none;
      -ms-overflow-style: none;
    }
    .metal-scroll-host::-webkit-scrollbar {
      display: none;
      width: 0;
      height: 0;
    }
    .metal-scroll-track {
      position: absolute;
      /*
       * z-index 5 keeps the track above ordinary scrolled content but
       * below the inspector scrim (z-index 8) and the system menu
       * panel (z-index 100). Without this, the custom scrollbar
       * floated over the dismissive scrim/inspector overlay.
       */
      z-index: 5;
      background:
        linear-gradient(90deg, rgba(0, 0, 0, 0.72), rgba(20, 17, 13, 0.55), rgba(0, 0, 0, 0.72)),
        #0a0806;
      box-shadow:
        inset 1px 0 0 rgba(0, 0, 0, 0.85),
        inset -1px 0 0 rgba(168, 133, 63, 0.18);
      cursor: pointer;
      pointer-events: auto;
      opacity: 0;
      transition: opacity 200ms ease;
    }
    .metal-scroll-track.is-visible {
      opacity: 0.85;
    }
    .metal-scroll-track.is-hovered,
    .metal-scroll-track.is-active {
      opacity: 1;
    }
    .metal-scroll-thumb {
      position: absolute;
      left: 1px;
      right: 1px;
      border: 1px solid rgba(0, 0, 0, 0.85);
      background-image: url("/textures/gold.jpg");
      background-size: 400px 400px;
      background-position: center;
      cursor: grab;
      transition: filter 120ms ease;
    }
    .metal-scroll-thumb::after {
      content: "";
      position: absolute;
      inset: 0;
      /*
       * Perfect 45-degree mitered chamfer.
       * CSS borders naturally meet at 45-degree angles. A semi-transparent
       * border tints the gold texture underneath it, creating lit and
       * shadowed faces of the same metal rather than flat plastic strips.
       */
      border-style: solid;
      border-width: 2px;
      border-top-color: rgba(255, 245, 200, 0.65);
      border-left-color: rgba(255, 245, 200, 0.25);
      border-bottom-color: rgba(30, 15, 5, 0.90);
      border-right-color: rgba(30, 15, 5, 0.60);
      pointer-events: none;
    }
    .metal-scroll-thumb:hover {
      filter: brightness(1.10) saturate(1.10);
    }
    .metal-scroll-thumb.is-dragging {
      cursor: grabbing;
      filter: brightness(0.85) saturate(1.10);
    }
  `;
  document.head.appendChild(style);
}

/* Position the track to overlay the viewport's right edge. We use
 * the viewport's offsetParent chain so the track positions correctly
 * regardless of where it ended up in the DOM. */
function syncTrackPosition(state: MetalScrollState): void {
  const { viewport, track } = state;
  const parent = track.parentElement;
  if (parent === null) return;
  const vpRect = viewport.getBoundingClientRect();
  const parentRect = parent.getBoundingClientRect();
  track.style.top = `${vpRect.top - parentRect.top}px`;
  track.style.left = `${vpRect.right - parentRect.left - state.width}px`;
  track.style.width = `${state.width}px`;
  track.style.height = `${vpRect.height}px`;
}

function updateThumb(state: MetalScrollState): void {
  const { viewport, track, thumb, minThumb } = state;
  const { clientHeight, scrollHeight, scrollTop } = viewport;
  if (scrollHeight <= clientHeight) {
    track.classList.remove("is-visible");
    return;
  }
  track.classList.add("is-visible");
  const ratio = clientHeight / scrollHeight;
  const thumbH = Math.max(minThumb, clientHeight * ratio);
  const maxThumbY = clientHeight - thumbH;
  const maxScroll = scrollHeight - clientHeight;
  const thumbY = maxScroll > 0 ? (scrollTop / maxScroll) * maxThumbY : 0;
  thumb.style.height = `${thumbH}px`;
  thumb.style.top = `${thumbY}px`;
  syncTrackPosition(state);
}

/* Find a non-static ancestor to host the absolute-positioned track.
 * If none exists we promote the immediate parent to `position:
 * relative` since adding a relative-positioning context to a wrapper
 * is the least invasive change. */
function findOrCreatePositionedParent(viewport: HTMLElement): HTMLElement {
  let ancestor: HTMLElement | null = viewport.parentElement;
  while (ancestor !== null) {
    const cs = window.getComputedStyle(ancestor);
    if (cs.position !== "static") return ancestor;
    ancestor = ancestor.parentElement;
  }
  // Fallback: promote the immediate parent.
  const parent = viewport.parentElement;
  if (parent === null) return document.body;
  parent.style.position = "relative";
  return parent;
}

function attach(state: MetalScrollState): () => void {
  const { viewport, track, thumb } = state;

  const onScroll = (): void => updateThumb(state);
  const onTrackEnter = (): void => track.classList.add("is-hovered");
  const onTrackLeave = (): void => track.classList.remove("is-hovered");

  const onThumbPointerDown = (e: PointerEvent): void => {
    e.preventDefault();
    e.stopPropagation();
    state.dragging = true;
    state.dragStartY = e.clientY;
    state.dragStartScrollTop = viewport.scrollTop;
    thumb.setPointerCapture(e.pointerId);
    thumb.classList.add("is-dragging");
    track.classList.add("is-active");
  };
  const onThumbPointerMove = (e: PointerEvent): void => {
    if (!state.dragging) return;
    const dy = e.clientY - state.dragStartY;
    const { clientHeight, scrollHeight } = viewport;
    const thumbH = thumb.offsetHeight;
    const maxThumbY = clientHeight - thumbH;
    const maxScroll = scrollHeight - clientHeight;
    if (maxThumbY <= 0) return;
    const next = state.dragStartScrollTop + (dy / maxThumbY) * maxScroll;
    viewport.scrollTop = Math.max(0, Math.min(maxScroll, next));
  };
  const onThumbPointerUp = (e: PointerEvent): void => {
    if (!state.dragging) return;
    state.dragging = false;
    try {
      thumb.releasePointerCapture(e.pointerId);
    } catch {
      /* pointer already released */
    }
    thumb.classList.remove("is-dragging");
    track.classList.remove("is-active");
  };

  const onTrackClick = (e: MouseEvent): void => {
    if (e.target !== track) return;
    const rect = track.getBoundingClientRect();
    const y = e.clientY - rect.top;
    const { clientHeight, scrollHeight } = viewport;
    const thumbH = thumb.offsetHeight;
    const targetThumbY = y - thumbH / 2;
    const maxThumbY = clientHeight - thumbH;
    const maxScroll = scrollHeight - clientHeight;
    const clampedThumbY = Math.max(0, Math.min(maxThumbY, targetThumbY));
    viewport.scrollTop =
      maxThumbY > 0 ? (clampedThumbY / maxThumbY) * maxScroll : 0;
  };

  const onWindowResize = (): void => updateThumb(state);

  viewport.addEventListener("scroll", onScroll, { passive: true });
  track.addEventListener("mouseenter", onTrackEnter);
  track.addEventListener("mouseleave", onTrackLeave);
  track.addEventListener("click", onTrackClick);
  thumb.addEventListener("pointerdown", onThumbPointerDown);
  thumb.addEventListener("pointermove", onThumbPointerMove);
  thumb.addEventListener("pointerup", onThumbPointerUp);
  thumb.addEventListener("pointercancel", onThumbPointerUp);
  window.addEventListener("resize", onWindowResize);

  state.resizeObserver.observe(viewport);
  // Observe children for content size changes that affect scrollHeight.
  for (const child of Array.from(viewport.children)) {
    state.resizeObserver.observe(child as Element);
  }
  state.mutationObserver.observe(viewport, {
    childList: true,
    subtree: true,
    characterData: true,
  });

  updateThumb(state);

  return (): void => {
    viewport.removeEventListener("scroll", onScroll);
    track.removeEventListener("mouseenter", onTrackEnter);
    track.removeEventListener("mouseleave", onTrackLeave);
    track.removeEventListener("click", onTrackClick);
    thumb.removeEventListener("pointerdown", onThumbPointerDown);
    thumb.removeEventListener("pointermove", onThumbPointerMove);
    thumb.removeEventListener("pointerup", onThumbPointerUp);
    thumb.removeEventListener("pointercancel", onThumbPointerUp);
    window.removeEventListener("resize", onWindowResize);
    state.resizeObserver.disconnect();
    state.mutationObserver.disconnect();
  };
}

export function metalScroll(
  viewport: HTMLElement,
  options: MetalScrollOptions = {},
): { destroy(): void; update(o: MetalScrollOptions): void } {
  ensureStylesInjected();

  const width = options.width ?? 18;
  const minThumb = options.minThumb ?? 36;

  viewport.classList.add("metal-scroll-host");

  const positioned = findOrCreatePositionedParent(viewport);

  const track = document.createElement("div");
  track.className = "metal-scroll-track";
  const thumb = document.createElement("div");
  thumb.className = "metal-scroll-thumb";
  track.appendChild(thumb);
  positioned.appendChild(track);

  const state: MetalScrollState = {
    viewport,
    track,
    thumb,
    resizeObserver: new ResizeObserver(() => updateThumb(state)),
    mutationObserver: new MutationObserver(() => updateThumb(state)),
    width,
    minThumb,
    dragging: false,
    dragStartY: 0,
    dragStartScrollTop: 0,
  };

  // Add right padding to viewport to prevent content from flowing under the scrollbar
  const originalPadding = viewport.style.paddingRight;
  const computedPadding = window.getComputedStyle(viewport).paddingRight;
  viewport.style.paddingRight = `calc(${computedPadding} + ${width}px)`;

  const detach = attach(state);

  return {
    destroy(): void {
      detach();
      viewport.style.paddingRight = originalPadding;
      viewport.classList.remove("metal-scroll-host");
      track.remove();
    },
    update(next: MetalScrollOptions): void {
      if (typeof next.width === "number" && next.width !== state.width) {
        state.width = next.width;
        track.style.width = `${next.width}px`;
        syncTrackPosition(state);
      }
      if (typeof next.minThumb === "number") {
        state.minThumb = next.minThumb;
        updateThumb(state);
      }
    },
  };
}
