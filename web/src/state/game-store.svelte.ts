// Svelte 5 runes-based store for the entire client.
//
// Why a single store instead of one-store-per-feature:
// - The backend always returns the whole GameState, so the natural unit of
//   reactivity is "the whole game". Splitting would introduce cross-store
//   ordering bugs (e.g. "did the chaos factor update before the action log?").
// - The dice-tumble animation needs to know about pending oracle calls, so
//   the latest pending OracleOutcome and the in-flight request live in the
//   same state object as the persisted state.

import { api } from "../lib/api";
import { saveOocNotes } from "./save/ooc-notes";
import { CampaignWorkflow, type ClientNote } from "./play";
import { SaveLibraryWorkflow, type LibraryStatus } from "./save";
import {
  RuntimeSettingsWorkflow,
  type CredentialSetupStatus,
  type LlmSettingsStatus,
  type RuntimeBootstrapStatus,
} from "./runtime";
import { emptyStreamingState, StreamWorkflow, type RollPhase, type StreamingState } from "./stream";
import type {
  CampaignEndReason,
  CampaignSeed,
  CharacterQuiz,
  CharacterQuizAnswer,
  CharacterSheet,
  GameState,
  Likelihood,
  LLMProvider,
  LLMPreset,
  LLMSettingsResponse,
  OracleOutcome,
  SaveSummary,
} from "../lib/types";

export type { StageProgress } from "./stream-runner";

// Inline "system message" that the chat surfaces alongside server events.
// We keep these client-only because they're transient feedback (help
// text, slash-error hints) and don't belong in the persisted action log.
//
// F-10 added an `explanation` kind for the OOC rules explainer. Those
// notes carry both the player's question and the LLM's answer so the
// chat surface can render them as a single OOC card (instead of two
// disjoint bubbles). They live in the same ephemeral buffer as help/
// error/info notes — reload clears them, the action log never sees
// them, and they never round-trip through `memory.json`.
export type { ClientNote } from "./play";

// F-12 save library state. We model the library as a discriminated
// status rather than a "ready vs not-ready" boolean because the
// app shell has three distinct splashes to render:
//   - "loading"   : we haven't yet finished the bootstrap call,
//                   so we can't tell whether to show the selector
//                   or auto-load play.
//   - "empty"     : the bootstrap call returned and there are no
//                   saves on disk — the only legal action is to
//                   start a fresh campaign.
//   - "selecting" : the player explicitly opened the save library
//                   from the system menu mid-session. We need to
//                   keep the rest of the app intact (current state,
//                   chat history) until the player picks a save,
//                   so we keep `state` populated while the splash
//                   is open.
//   - "ready"     : an active save is bound and `state` is the
//                   live `GameState` for that save. This is the
//                   normal play path.
// Modeling them as a union forces every consumer to handle the
// loading/empty branches, which we'd otherwise drift on.
export type { LibraryStatus } from "./save";

// LLM settings modal lifecycle. Mirrors `LibraryStatus` in spirit:
// modeling each phase as a discriminated string forces consumers to
// branch exhaustively rather than juggling a `loading: boolean` plus
// a nullable `error`.
//   - "idle"    : modal closed; no settings payload cached.
//   - "loading" : the modal just opened (or refreshed); we're awaiting
//                 the GET on `/settings/llm`.
//   - "ready"   : the GET succeeded and `settings` is the latest
//                 server-canonical payload.
//   - "saving"  : the player picked a different preset and the POST is
//                 in flight. The picker stays read-only during this
//                 phase so a double-click can't queue two swaps.
//   - "error"   : the GET failed. `settingsError` carries the message.
//                 Distinct from "ready + post failure" because we still
//                 want to render the cached settings while showing a
//                 transient save error inline.
export type { CredentialSetupStatus, LlmSettingsStatus, RuntimeBootstrapStatus } from "./runtime";

// F-09 cross-component scroll request. The Inspector commands the
// ChatFeed to scroll a particular event into view (oracle deep-link,
// transcript search hit). We model this as a one-shot signal with a
// rotating sequence number rather than a plain `eventId | null`
// because a sequence of clicks on the *same* eventId has to re-trigger
// the scroll/flash effect — without `seq`, Svelte's reactivity would
// see "the same value" and skip the run.
export interface ScrollRequest {
  eventId: string;
  seq: number;
}

export type InspectorSection = "threads" | "npcs";

// H-02 cross-surface continuity jump. A receipt pill can ask the
// inspector to open a specific section and focus one referenced entity.
// The rotating seq mirrors ScrollRequest so repeated clicks on the same
// pill still re-trigger the drawer-open / highlight effect.
export interface InspectorFocusRequest {
  section: InspectorSection;
  entityId: string | null;
  seq: number;
}

// Note: never write `$state<T>(...)` with explicit type arguments. Svelte 5
// silently initializes the rune to `undefined` in that case (the type-arg
// syntax is treated as an untyped call). Use a separate annotation on the
// declaration when you need to widen / narrow the inferred type.
class GameStore {
  state: GameState | null = $state(null);
  isLoading: boolean = $state(false);
  error: string | null = $state(null);
  rollPhase: RollPhase = $state("idle");
  pendingOracle: OracleOutcome | null = $state(null);
  cancelLabel: string | null = $state(null);

  // Provisional streaming buffer. While `streaming.active` is true, the
  // chat feed renders a provisional DM bubble that mirrors `content`,
  // a thinking bubble that mirrors `thinking`, and a receipt pinned to
  // `pendingOutcome`. On stream completion, the canonical event lands
  // in `state.action_log` and the provisional bubble is replaced
  // wholesale — no delta merging, no "did this token come from the
  // stream or the final?" reconciliation logic.
  streaming: StreamingState = $state(emptyStreamingState());

  // Client-only ephemeral messages (slash-help, slash-error). They live
  // alongside the server-canonical action log in the chat feed.
  notes: ClientNote[] = $state([]);

  // Inspector drawer visibility. Lives here (not on App.svelte) so any
  // component - e.g. a chat receipt's "show full mechanics" link - can
  // command the drawer to open without prop drilling.
  inspectorOpen: boolean = $state(false);

  // F-09 history-browser scroll target. Set by `requestScrollTo` and
  // cleared once the ChatFeed has consumed it. The seq counter
  // rotates so identical-eventId requests still fire the scroll/flash
  // effect — see the ScrollRequest type doc.
  scrollRequest: ScrollRequest | null = $state(null);
  #scrollSeq = 0;
  inspectorFocusRequest: InspectorFocusRequest | null = $state(null);
  #inspectorFocusSeq = 0;

  // F-12 Save library --------------------------------------------------------
  //
  // `library` is the canonical list of saves and `activeSaveId` is the
  // one bound to `state`. We deliberately keep `library` flat at the
  // store level (not nested behind another object) because the StatusStrip
  // hamburger menu and the SaveLibrary splash both subscribe to it
  // independently — flat fields keep Svelte 5's reactivity cheap
  // without forcing both consumers to share a derived selector.
  library: SaveSummary[] = $state([]);
  activeSaveId: string | null = $state(null);
  libraryStatus: LibraryStatus = $state("loading");
  // Distinct from `state.error`: a library failure (bootstrap, switch)
  // can happen before any save is bound, so a top-level surface needs
  // its own error sink. The splash screen renders this verbatim.
  libraryError: string | null = $state(null);

  // Runtime bootstrap / BYOK --------------------------------------------------
  //
  // Packaged builds need an app-level readiness gate before campaign
  // bootstrap. If no Gemini/OpenRouter key exists (stored credential or
  // developer `.env`), the player must configure one before the save
  // library and campaign generation become useful. This sits above any
  // one save because provider credentials are runtime config, not campaign
  // canon.
  runtimeStatus: RuntimeBootstrapStatus = $state("checking");
  runtimeError: string | null = $state(null);
  credentialSetupOpen: boolean = $state(false);
  credentialSetupProvider: LLMProvider = $state("openrouter");
  credentialSetupStatus: CredentialSetupStatus = $state("idle");
  credentialSetupError: string | null = $state(null);

  // LLM settings modal -------------------------------------------------------
  //
  // We keep the picker out of the canonical `GameState` because the
  // backend does the same thing — the active preset lives in
  // `data/runtime_settings.json`, not in any save's memory. The
  // store only caches the most recent payload (loaded on modal open
  // or after a successful save) so the SettingsModal has something
  // to render without re-fetching on every keystroke.
  //
  // Open/close lives on the store rather than the modal component so
  // any surface (system menu, status strip, future quick-action) can
  // command "open settings" with one call. The modal subscribes to
  // `settingsStatus` to decide whether to render a spinner, the
  // picker, or a load-error fallback.
  settingsOpen: boolean = $state(false);
  settingsStatus: LlmSettingsStatus = $state("idle");
  settings: LLMSettingsResponse | null = $state(null);
  // GET-side error. The modal renders this in place of the picker
  // when the initial load fails so the player knows the backend
  // didn't respond, not that "kimi" really is the only available
  // option.
  settingsError: string | null = $state(null);
  // POST-side error, kept separate so the modal can render the
  // cached `settings` payload alongside a transient "couldn't save"
  // message (e.g. 409 while a turn is mid-stream — the backend's
  // `_guard_request_idle` rejects swaps until the player's turn
  // settles).
  settingsSaveError: string | null = $state(null);
  #streamWorkflow = new StreamWorkflow(this);
  #saveWorkflow = new SaveLibraryWorkflow(this, this.#streamWorkflow);
  #runtimeWorkflow = new RuntimeSettingsWorkflow(this, () => this.bootstrap());
  #campaignWorkflow = new CampaignWorkflow(this, this.#streamWorkflow);

  // Derived: the most recent oracle outcome on the persisted state. Exposed
  // as a getter (via `$derived.by`) so the dice tumbler can subscribe and
  // re-animate when this changes.
  latestOutcome: OracleOutcome | null = $derived.by(() => {
    if (!this.state || this.state.oracle_history.length === 0) return null;
    return this.state.oracle_history[this.state.oracle_history.length - 1] ?? null;
  });

  async refresh(): Promise<void> {
    await this.#streamWorkflow.runState((signal) => api.getState(signal));
  }

  async bootstrapRuntime(): Promise<void> {
    await this.#runtimeWorkflow.bootstrap();
  }

  /**
   * F-12 startup bootstrap. Calls `/api/library/bootstrap`, then either
   *   (a) auto-loads the active save's `GameState` and transitions to
   *       `libraryStatus: "ready"` — this is the steady-state launch
   *       experience the user asked for ("if a campaign exists, just
   *       load it"); or
   *   (b) sets `libraryStatus: "empty"` and lets the SaveLibrary splash
   *       render the "begin your first campaign" prompt.
   *
   * The selected id is not published until `getState` succeeds. If the
   * state fetch fails, the library remains visible with its error and the
   * previous id/state binding stays intact instead of briefly pairing the
   * new id with stale campaign data.
   */
  async bootstrap(): Promise<void> {
    await this.#saveWorkflow.bootstrap();
  }

  /**
   * F-12 create a new save slot and (by default) immediately select it.
   *
   * Why we always reset client-side ephemera on a save switch:
   *   `notes`, the provisional streaming buffer, and the scroll request
   *   are all keyed off the *current save's* event stream. Carrying any
   *   of them across a switch would mean the new campaign opens with
   *   stale OOC bubbles, mid-stream artifacts, or scroll requests that
   *   point at event ids that no longer exist. Clearing here keeps the
   *   switch atomic — the new save's `GameState` is the only thing the
   *   chat surface reads, and there's nothing left over to filter out.
   *
   * `select=false` exists for an eventual "stage a save without leaving
   * the current campaign" UX (we don't ship that surface in v1, but the
   * backend already supports it and exposing the parameter keeps the
   * call sites uniform).
   */
  async createSave(select = true): Promise<string | null> {
    return await this.#saveWorkflow.create(select);
  }

  /**
   * F-12 switch the active save. The backend rejects this with 409
   * while a streamed request is in flight (see
   * `_guard_save_library_idle`), so we don't try to be clever about
   * cancelling first — letting the player see "Cannot switch saves
   * while a request is still in flight." is the cleaner contract than
   * silently aborting their current turn under them.
   *
   * On success we wholesale replace `state` and clear ephemera, the
   * same way `createSave` does.
   */
  async selectSave(saveId: string): Promise<void> {
    await this.#saveWorkflow.select(saveId);
  }

  /**
   * F-12 open the save library splash mid-session. We keep `state`
   * populated so that hitting "Cancel" (or hardware back) returns to
   * the live campaign without a refetch, and so the splash can show
   * the active save's "you are here" cue without re-asking the server.
   */
  openLibrary(): void {
    this.#saveWorkflow.open();
  }

  /**
   * F-12 close the splash without switching. Only valid when an active
   * save is loaded; the empty-library splash is a hard stop until a
   * save is created.
   */
  closeLibrary(): void {
    this.#saveWorkflow.close();
  }

  /**
   * Open the LLM settings modal and (re-)fetch the current preset.
   *
   * We always re-fetch on open instead of trusting the cached payload
   * because the active preset can change out-of-band (another tab,
   * a manual edit to `data/runtime_settings.json`) and stale cards
   * would mislead the player into thinking "Kimi" is checked when
   * "Gemini split" is actually live. The modal renders the cached
   * payload optimistically while the refresh runs so the picker
   * feels instant after the first open.
   */
  async openSettings(): Promise<void> {
    await this.#runtimeWorkflow.openSettings();
  }

  closeSettings(): void {
    this.#runtimeWorkflow.closeSettings();
  }

  /**
   * Persist a new active LLM preset.
   *
   * Returns `true` on success so the modal can chain a close-on-save
   * UX without having to subscribe to `settingsStatus`. On failure
   * (network / 409 in-flight guard / unavailable preset) we surface
   * the message on `settingsSaveError` and keep the modal open with
   * the previous selection still highlighted — the player can then
   * wait for a streamed turn to finish or fix their `.env` and try
   * again.
   */
  async updateLlmPreset(preset: LLMPreset): Promise<boolean> {
    return await this.#runtimeWorkflow.updatePreset(preset);
  }

  openCredentialSetup(provider: LLMProvider): void {
    this.#runtimeWorkflow.openCredentialSetup(provider);
  }

  closeCredentialSetup(): void {
    this.#runtimeWorkflow.closeCredentialSetup();
  }

  async saveLlmCredentials(provider: LLMProvider, apiKey: string): Promise<boolean> {
    return await this.#runtimeWorkflow.saveCredentials(provider, apiKey);
  }

  async reset(): Promise<void> {
    await this.#campaignWorkflow.reset();
  }

  async setChaos(value: number): Promise<void> {
    await this.#campaignWorkflow.setChaos(value);
  }

  async updateNotes(settingNotes: string, playerNotes: string): Promise<void> {
    await this.#campaignWorkflow.updateNotes(settingNotes, playerNotes);
  }

  async updateDirectives(worldGuidance: string, playGuidance: string): Promise<void> {
    await this.#campaignWorkflow.updateDirectives(worldGuidance, playGuidance);
  }

  async updateCampaignSeed(seed: CampaignSeed): Promise<void> {
    await this.#campaignWorkflow.updateCampaignSeed(seed);
  }

  async askYesNo(question: string, likelihood: Likelihood): Promise<void> {
    await this.#campaignWorkflow.askYesNo(question, likelihood);
  }

  async randomEvent(): Promise<void> {
    await this.#campaignWorkflow.randomEvent();
  }

  async sceneCheck(expectedScene: string): Promise<void> {
    await this.#campaignWorkflow.sceneCheck(expectedScene);
  }

  async submitAction(action: string): Promise<void> {
    await this.#campaignWorkflow.submitAction(action);
  }

  async explain(question: string): Promise<void> {
    await this.#campaignWorkflow.explain(question);
  }

  async submitTurn(text: string): Promise<void> {
    await this.#campaignWorkflow.submitTurn(text);
  }

  async fetchCharacterTemplates(): Promise<CharacterSheet[]> {
    return await this.#campaignWorkflow.fetchCharacterTemplates();
  }

  async generateCharacterDraft(
    mode: "scratch" | "template",
    prompt?: string,
    template?: CharacterSheet,
  ): Promise<CharacterSheet | null> {
    return await this.#campaignWorkflow.generateCharacterDraft(mode, prompt, template);
  }

  async generateCharacterQuiz(concept: string): Promise<CharacterQuiz | null> {
    return await this.#campaignWorkflow.generateCharacterQuiz(concept);
  }

  async generateQuizzedCharacterDraft(
    concept: string,
    answers: CharacterQuizAnswer[],
    finalNote: string | null,
  ): Promise<CharacterSheet | null> {
    return await this.#campaignWorkflow.generateQuizzedCharacterDraft(concept, answers, finalNote);
  }

  async finalizeCharacter(character: CharacterSheet): Promise<void> {
    await this.#campaignWorkflow.finalizeCharacter(character);
  }

  async endCampaign(reason: CampaignEndReason, summary: string): Promise<void> {
    await this.#campaignWorkflow.endCampaign(reason, summary);
  }

  async startCampaign(): Promise<void> {
    await this.#campaignWorkflow.startCampaign();
  }

  async regenerateMessage(eventId: string): Promise<void> {
    await this.#campaignWorkflow.regenerateMessage(eventId);
  }

  async submit(rawText: string): Promise<boolean> {
    return await this.#campaignWorkflow.submit(rawText);
  }

  toggleInspector(): void {
    this.inspectorOpen = !this.inspectorOpen;
  }

  openInspector(): void {
    this.inspectorOpen = true;
  }

  /**
   * F-09 cross-component scroll. The Inspector calls this when the
   * player clicks an oracle row's "Show in chat" link or a search hit
   * — `eventId` must be the canonical event id from `action_log` (or
   * the synthesized `opening_<state-id>` for the very first DM beat).
   * We bump the sequence counter on every call so back-to-back
   * requests for the same eventId still re-trigger the feed's
   * scroll/flash effect.
   *
   * Closing the Inspector is the caller's choice, not this method's:
   * "scroll to a row" is sometimes paired with "and keep the panel
   * open so I can scan more results", and sometimes paired with
   * "close the panel out of my way". The signal stays orthogonal.
   */
  requestScrollTo(eventId: string): void {
    this.#scrollSeq += 1;
    this.scrollRequest = { eventId, seq: this.#scrollSeq };
  }

  /**
   * Called by the ChatFeed once it has applied the scroll. Clears
   * the request so a re-render of the feed (e.g. after a stream
   * finalizes) doesn't replay the scroll a second time.
   */
  consumeScrollRequest(): void {
    this.scrollRequest = null;
  }

  /**
   * H-02 receipt-link navigation. Opens the Inspector and asks it to
   * reveal a specific section/entity. This intentionally stays parallel
   * to `requestScrollTo` instead of overloading it — the chat feed and
   * the inspector solve different navigation problems.
   */
  requestInspectorFocus(section: InspectorSection, entityId: string | null = null): void {
    this.#inspectorFocusSeq += 1;
    this.inspectorOpen = true;
    this.inspectorFocusRequest = {
      section,
      entityId,
      seq: this.#inspectorFocusSeq,
    };
  }

  consumeInspectorFocusRequest(): void {
    this.inspectorFocusRequest = null;
  }

  dismissNote(id: string): void {
    const wasExplanation = this.notes.some((n) => n.id === id && n.kind === "explanation");
    this.notes = this.notes.filter((n) => n.id !== id);
    // OOC notes survive reloads (see save/ooc-notes.ts), so a dismissal
    // has to write through to localStorage as well — otherwise the
    // dismissed entry would re-appear on next bootstrap.
    if (wasExplanation) {
      saveOocNotes(this.activeSaveId, this.notes);
    }
  }

  cancelCurrentRequest(): void {
    this.#streamWorkflow.cancel();
  }

  // True only while a stream is active for chat-flavored output. The
  // chat feed uses this to render a provisional DM bubble, and the
  // composer uses it to keep the cancel button labeled correctly.
  // This is exposed as a getter (rather than a duplicate $state field)
  // so there's exactly one source of truth: `streaming.active`.
  get isStreaming(): boolean {
    return this.streaming.active;
  }
}

export const game = new GameStore();
