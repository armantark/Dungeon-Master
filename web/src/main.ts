import { mount } from "svelte";
import App from "./App.svelte";
import { initializeDesktopApiBase } from "./lib/desktop";
import "./styles/app.css";

const target = document.getElementById("app");
if (!target) {
  throw new Error("#app mount node missing from index.html");
}

await initializeDesktopApiBase().catch((error: unknown) => {
  console.error("Failed to initialize desktop runtime.", error);
});

const app = mount(App, { target });

export default app;
