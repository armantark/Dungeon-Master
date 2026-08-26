import { mount } from "svelte";
import App from "./App.svelte";
import { shouldMountArchitecture } from "./lib/dev-route";
import { initializeDesktopApiBase } from "./lib/desktop";
import { initGlobalTextureRandomization } from "./lib/randomTexturePosition";
import "./styles/app.css";

const target = document.getElementById("app");
if (!target) {
  throw new Error("#app mount node missing from index.html");
}

let showArchitecture = false;
let ArchitectureRoot: typeof App | null = null;

if (
  import.meta.env.DEV &&
  shouldMountArchitecture(
    window.location.pathname,
    true,
    import.meta.env.VITE_ENABLE_ARCHITECTURE_MAP === "true",
  )
) {
  showArchitecture = true;
  // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion -- svelte-check preserves component binding metadata that typed ESLint erases for this lazy import.
  ArchitectureRoot = (await import("./ArchitectureApp.svelte")).default as typeof App;
}

if (!showArchitecture) {
  await initializeDesktopApiBase().catch((error: unknown) => {
    console.error("Failed to initialize desktop runtime.", error);
  });
}

// Start randomizing --btn-tex-x and y on all buttons globally
initGlobalTextureRandomization();

const app = ArchitectureRoot ? mount(ArchitectureRoot, { target }) : mount(App, { target });

export default app;
