/*
 * Global texture position randomizer.
 * 
 * Automatically assigns `--btn-tex-x` and `--btn-tex-y` custom properties
 * to all cast-iron textured UI elements (`button`, `.btn`, `.scene`) 
 * as they enter the DOM.
 *
 * This ensures that stacks of sibling buttons with identical dimensions
 * (like Inspector menus, save-load chips) don't show the exact same crop
 * of the source texture image.
 */

function assignRandomPosition(el: HTMLElement) {
  if (el.hasAttribute("data-tex-assigned")) return;
  const x = Math.floor(Math.random() * 100);
  const y = Math.floor(Math.random() * 100);
  el.style.setProperty("--btn-tex-x", `${x}%`);
  el.style.setProperty("--btn-tex-y", `${y}%`);
  el.setAttribute("data-tex-assigned", "true");
}

export function initGlobalTextureRandomization() {
  // Apply to already existing elements
  document.querySelectorAll("button, .btn, .scene").forEach((el) => {
    assignRandomPosition(el as HTMLElement);
  });

  // Watch for new elements added to the DOM
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          const el = node as HTMLElement;
          if (el.matches && el.matches("button, .btn, .scene")) {
            assignRandomPosition(el);
          }
          if (el.querySelectorAll) {
            el.querySelectorAll("button, .btn, .scene").forEach((child) => {
              assignRandomPosition(child as HTMLElement);
            });
          }
        }
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
}

/**
 * Legacy Svelte action, kept for backwards compatibility if still used
 * on a specific element.
 */
interface Options {
  seed?: number;
}

export function randomTexturePosition(
  el: HTMLElement,
  opts: Options = {},
): { destroy(): void } {
  const rand = opts.seed !== undefined ? mulberry32(opts.seed) : Math.random;
  const x = Math.floor(rand() * 100);
  const y = Math.floor(rand() * 100);
  el.style.setProperty("--btn-tex-x", `${x}%`);
  el.style.setProperty("--btn-tex-y", `${y}%`);
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
