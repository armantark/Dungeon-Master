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
