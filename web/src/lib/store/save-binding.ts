import type { GameState } from "../types";

export interface SaveBinding {
  saveId: string;
  state: GameState;
}

/**
 * Fetch the state for a selected save before publishing either value.
 * Callers can then replace the save id and state synchronously, so no
 * render can observe a new save id paired with the previous save's state.
 */
export async function fetchSaveBinding(
  saveId: string,
  fetchState: () => Promise<GameState>,
): Promise<SaveBinding> {
  return { saveId, state: await fetchState() };
}
