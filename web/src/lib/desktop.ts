import { invoke } from "@tauri-apps/api/core";

import { api, setApiBase } from "./api";

const HEALTH_RETRY_ATTEMPTS = 40;
const HEALTH_RETRY_DELAY_MS = 250;

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function initializeDesktopApiBase(): Promise<void> {
  if (!isTauriRuntime()) return;
  const base = await invoke<string>("desktop_api_base");
  setApiBase(base);
  await waitForBackendHealth();
}

async function waitForBackendHealth(): Promise<void> {
  for (let attempt = 0; attempt < HEALTH_RETRY_ATTEMPTS; attempt += 1) {
    try {
      await api.health();
      return;
    } catch {
      await sleep(HEALTH_RETRY_DELAY_MS);
    }
  }
  throw new Error("Dungeon Master backend failed to start.");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
