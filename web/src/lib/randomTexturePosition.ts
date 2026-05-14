/*
 * `randomTexturePosition` — Svelte action that assigns a random
 * `background-position` to a button's cast-iron `::before` pseudo on
 * mount, then leaves the element alone. The button rule reads those
 * coordinates from CSS custom properties (`--btn-tex-x`, `--btn-tex-y`)
 * with sensible 50%/50% fallbacks for the global default.
 *
 * Why this exists:
 *   The default `button::before { background-size: cover; }` scales the
 *   cast-iron texture to the button's exact bounds. For stacks of
 *   sibling buttons with identical dimensions (the Inspector's
 *   `Drawer` flaps, save-load chips, common-action pills, etc.), every
 *   sibling shows the same crop of the source image — the stack reads
 *   as wallpaper rather than a row of independent iron plates.
 *
 *   `background-attachment: fixed` looks tempting as a free way to get
 *   per-element variation (each element samples its viewport-relative
 *   slice of a single texture sheet), but it causes the "blank dark
 *   patch" bug: buttons that land on uniformly-dark regions of the
 *   texture appear to have no texture at all. See
 *   `memory-bank/systemPatterns.md` ("Texture / button rendering
 *   pitfalls", pitfall 3).
 *
 *   This action instead picks a stable random position per element on
 *   first mount and pins it via inline custom properties, so the
 *   sibling stack reads as varied without depending on viewport
 *   geometry.
 */

interface Options {
  /**
   * Optional deterministic seed. If provided, the same element + seed
   * always picks the same offset (useful for tests). Default: a true
   * `Math.random()` pair, freshly chosen per mount.
   */
  seed?: number;
}

/**
 * Apply a per-instance random `background-position` to a button.
 * The CSS rule reads it from `--btn-tex-x` / `--btn-tex-y` custom
 * properties on the element, so the element must be the button
 * itself (not a wrapping div).
 */
export function randomTexturePosition(
  el: HTMLElement,
  opts: Options = {},
): { destroy(): void } {
  const seed = opts.seed;
  const rand = typeof seed === "number" ? mulberry32(seed) : Math.random;
  // Stay within 0–100% of the texture so we never expose its edges
  // when paired with `background-size: cover` (cover always upscales
  // to fit, so the texture is at least as large as the element on its
  // shorter axis; picking a percentage shifts the crop window without
  // exposing a seam).
  const x = `${Math.floor(rand() * 100)}%`;
  const y = `${Math.floor(rand() * 100)}%`;
  el.style.setProperty("--btn-tex-x", x);
  el.style.setProperty("--btn-tex-y", y);
  return {
    destroy(): void {
      el.style.removeProperty("--btn-tex-x");
      el.style.removeProperty("--btn-tex-y");
    },
  };
}

/* Deterministic PRNG used when a seed is supplied (test paths). */
function mulberry32(a: number): () => number {
  let t = a;
  return function (): number {
    t = (t + 0x6d2b79f5) | 0;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}
