import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { game } from "./store.svelte";

describe("GameStore setup streaming", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    game.state = null;
    game.isLoading = false;
    game.error = null;
    game.rollPhase = "idle";
    game.pendingOracle = null;
    game.cancelLabel = null;
    game.streaming = {
      active: false,
      route: null,
      requestId: null,
      content: "",
      thinking: "",
      pendingOutcome: null,
      resuming: false,
      stages: [],
    };
    game.notes = [];
    game.inspectorOpen = false;
    game.scrollRequest = null;
    game.inspectorFocusRequest = null;
  });

  it("requestScrollTo bumps a unique seq for repeat calls so the feed re-fires", () => {
    // Repeat clicks on the same eventId have to re-trigger the
    // scroll/flash effect — without a rotating seq, Svelte's
    // $effect would see the same eventId and skip the run, which
    // would mean clicking "Show in chat" twice in a row only
    // works the first time.
    game.requestScrollTo("event_a");
    const first = game.scrollRequest;
    expect(first?.eventId).toBe("event_a");
    expect(first?.seq).toBeGreaterThan(0);

    game.requestScrollTo("event_a");
    const second = game.scrollRequest;
    expect(second?.eventId).toBe("event_a");
    expect(second?.seq).toBe((first?.seq ?? 0) + 1);
  });

  it("consumeScrollRequest clears the pending signal", () => {
    // The ChatFeed calls this once it has applied the scroll. If
    // the store kept the request around, a remount of the feed
    // (route change, dev HMR) would replay a stale jump out from
    // under the player.
    game.requestScrollTo("event_b");
    expect(game.scrollRequest).not.toBeNull();
    game.consumeScrollRequest();
    expect(game.scrollRequest).toBeNull();
  });

  it("requestInspectorFocus opens the inspector and bumps a unique seq for repeat clicks", () => {
    game.inspectorOpen = false;

    game.requestInspectorFocus("npcs", "npc_ash");
    const first = game.inspectorFocusRequest;

    expect(game.inspectorOpen).toBe(true);
    expect(first?.section).toBe("npcs");
    expect(first?.entityId).toBe("npc_ash");
    expect(first?.seq).toBeGreaterThan(0);

    game.requestInspectorFocus("npcs", "npc_ash");
    const second = game.inspectorFocusRequest;

    expect(second?.section).toBe("npcs");
    expect(second?.entityId).toBe("npc_ash");
    expect(second?.seq).toBe((first?.seq ?? 0) + 1);
  });

  it("translates /retreat into a free-text turn so the planner runs", async () => {
    const streamSpy = vi
      .spyOn(api, "streamSubmitTurn")
      .mockResolvedValue({ kind: "final" } as never);

    const consumed = await game.submit("/retreat down the chapel stair");

    expect(consumed).toBe(true);
    expect(streamSpy).toHaveBeenCalledTimes(1);
    const [textArg] = streamSpy.mock.calls[0]!;
    expect(textArg).toBe(
      "I attempt to retreat from combat: down the chapel stair",
    );
  });

  it("uses a neutral default text when /retreat has no reason", async () => {
    const streamSpy = vi
      .spyOn(api, "streamSubmitTurn")
      .mockResolvedValue({ kind: "final" } as never);

    await game.submit("/retreat");

    const [textArg] = streamSpy.mock.calls[0]!;
    expect(textArg).toBe("I attempt to retreat from combat.");
  });

  it("translates each acquisition verb into a free-text turn for the planner", async () => {
    // Same shape as /retreat: the slash translates to natural-language
    // first-person prose that the LLM-backed planner classifies as
    // ACQUIRE_ITEM. We assert the verb the player typed is preserved
    // verbatim because the resulting narration leans on that fictional
    // framing (looting vs. buying vs. taking).
    const streamSpy = vi
      .spyOn(api, "streamSubmitTurn")
      .mockResolvedValue({ kind: "final" } as never);

    const cases: Array<[string, string]> = [
      ["/loot the captain's chest", "I loot the captain's chest."],
      ["/take a wax-sealed letter", "I take a wax-sealed letter."],
      ["/buy rope and a lantern", "I buy rope and a lantern."],
      ["/acquire the gift Solyn offered me", "I acquire the gift Solyn offered me."],
    ];

    for (const [input, expected] of cases) {
      streamSpy.mockClear();
      const consumed = await game.submit(input);
      expect(consumed).toBe(true);
      expect(streamSpy).toHaveBeenCalledTimes(1);
      const [textArg] = streamSpy.mock.calls[0]!;
      expect(textArg).toBe(expected);
    }
  });

  it("does not append a trailing period if the body already ends in punctuation", async () => {
    // Player-authored sentences land verbatim. We only insert a period
    // when the body would otherwise read like a fragment; respecting
    // existing terminators avoids the planner seeing `…now!.` style
    // double-punctuation.
    const streamSpy = vi
      .spyOn(api, "streamSubmitTurn")
      .mockResolvedValue({ kind: "final" } as never);

    await game.submit("/loot the chest before the guards return!");

    const [textArg] = streamSpy.mock.calls[0]!;
    expect(textArg).toBe("I loot the chest before the guards return!");
  });

  it("surfaces a slash error and does not dispatch when /loot has no body", async () => {
    const streamSpy = vi.spyOn(api, "streamSubmitTurn");

    const consumed = await game.submit("/loot");

    expect(consumed).toBe(true);
    expect(streamSpy).not.toHaveBeenCalled();
    // The parser-authored error message lands as a client-only note so
    // the player sees what's missing without us shipping a request the
    // backend would have rejected anyway.
    expect(game.notes.some((n) => n.kind === "error" && n.text.includes("/loot"))).toBe(true);
  });

  it("keeps composer text available when a backend turn submission fails", async () => {
    vi.spyOn(api, "streamSubmitTurn").mockImplementation(
      (_text, handlers) => {
        handlers.onError?.({
          type: "error",
          message: "Turn planning failed before any deterministic resolution could be chosen.",
          code: "planning_failed",
          state: null,
        });
        return Promise.resolve({
          kind: "error",
          event: {
            type: "error",
            message: "Turn planning failed before any deterministic resolution could be chosen.",
            code: "planning_failed",
            state: null,
          },
        } as never);
      },
    );

    const consumed = await game.submit("I ask the patriarch's name.");

    expect(consumed).toBe(false);
    expect(game.error).toContain("Turn planning failed");
  });

  it("routes /retire through endCampaign with reason=retirement and the typed summary", async () => {
    // The terminal-close commands deliberately bypass the planner and
    // hit /campaign/end directly, so we spy on the api method rather
    // than the streaming turn surface. We pass null when the body is
    // empty so the backend's deterministic default fires; any
    // non-empty body is forwarded verbatim.
    const endSpy = vi
      .spyOn(api, "endCampaign")
      .mockResolvedValue({} as never);

    const consumed = await game.submit("/retire I lay the blade by the hearth.");

    expect(consumed).toBe(true);
    expect(endSpy).toHaveBeenCalledTimes(1);
    const [reasonArg, summaryArg] = endSpy.mock.calls[0]!;
    expect(reasonArg).toBe("retirement");
    expect(summaryArg).toBe("I lay the blade by the hearth.");
  });

  it("forwards null summary on a bare /victory so the backend writes its deterministic default", async () => {
    const endSpy = vi
      .spyOn(api, "endCampaign")
      .mockResolvedValue({} as never);

    await game.submit("/victory");

    const [reasonArg, summaryArg] = endSpy.mock.calls[0]!;
    expect(reasonArg).toBe("victory");
    // Empty bodies become null at the store boundary so the
    // backend's null-vs-non-null branch (deterministic default vs.
    // player-authored summary) fires correctly. We assert this here
    // because the alternative — sending "" — would slip past the
    // backend's `min_length=1` validator and 422 the request.
    expect(summaryArg).toBeNull();
  });

  it("dispatches /ask to the read-only preview endpoint and lands a session-only OOC note", async () => {
    const previewSpy = vi
      .spyOn(api, "previewYesNo")
      .mockResolvedValue({
        id: "oracle_preview_1",
        created_at: "2025-01-01T00:00:00Z",
        kind: "yes_no",
        summary: "Yes: Is the gate watched?",
        rolls: [{ label: "fate", result: 17, sides: 100 }],
        question: "Is the gate watched?",
        likelihood: "Likely",
        answer: "Yes",
        probability: 70,
        chaos_factor: 5,
        event_focus: null,
        event_action: null,
        event_tone: null,
        event_subject: null,
        referenced_thread_id: null,
        referenced_thread_ids: [],
        referenced_npc_id: null,
        referenced_npc_ids: [],
        scene_status: null,
        cairn: null,
      } as never);
    const committedSpy = vi.spyOn(api, "askYesNo");

    const consumed = await game.submit("/ask Is the gate watched? [likely]");

    expect(consumed).toBe(true);
    expect(previewSpy).toHaveBeenCalledTimes(1);
    expect(committedSpy).not.toHaveBeenCalled();
    const [questionArg, likelihoodArg] = previewSpy.mock.calls[0]!;
    expect(questionArg).toBe("Is the gate watched?");
    expect(likelihoodArg).toBe("Likely");
    const note = game.notes.find((n) => n.kind === "oracle_preview");
    expect(note).toBeDefined();
    expect(note?.question).toBe("Is the gate watched?");
    expect(note?.text).toContain("**Oracle preview**");
    expect(note?.text).toContain("**Adjusted chance:** 70%");
    expect(note?.text).toContain("does not commit the turn");
  });

  it("dispatches /explain to streamExplain and persists the answer as an ephemeral OOC note", async () => {
    // The OOC explainer must hit `streamExplain` (not the unary
    // `/explain` endpoint) on the happy path so the player gets
    // streamed feedback. We mock the streaming call to mimic a
    // real `final_payload` arrival by invoking the handler the
    // store wires up; that's how `#runStreamingPayload` extracts
    // the answer string. We also assert that the persisted note
    // is OOC (kind `"explanation"`) and carries the player's
    // verbatim question on the same record so the chat feed can
    // render a Q+A pair.
    const streamSpy = vi
      .spyOn(api, "streamExplain")
      .mockImplementation((_question, handlers) => {
        handlers.onFinalPayload?.({
          type: "final_payload",
          kind: "explanation",
          payload: { answer: "Atk targets a foe; the receipt records the d20 roll." },
          thinking: null,
        });
        return Promise.resolve({ kind: "final" } as never);
      });

    const consumed = await game.submit("/explain how does atk work?");

    expect(consumed).toBe(true);
    expect(streamSpy).toHaveBeenCalledTimes(1);
    const [questionArg] = streamSpy.mock.calls[0]!;
    expect(questionArg).toBe("how does atk work?");

    const oocNote = game.notes.find((n) => n.kind === "explanation");
    expect(oocNote).toBeDefined();
    expect(oocNote?.text).toContain("Atk targets a foe");
    expect(oocNote?.question).toBe("how does atk work?");
  });

  it("falls back to the unary /explain endpoint when the streaming route 404s, still landing an ephemeral OOC note", async () => {
    // Until the backend's `/api/explain/stream` route is universally
    // reachable, the store must keep working through the unary
    // `/api/explain` fallback. We simulate a transport-level 404 on
    // the streaming endpoint and confirm the fallback path produces
    // the same ephemeral OOC note the streaming path would.
    const { StreamTransportError } = await import("./api");
    vi.spyOn(api, "streamExplain").mockRejectedValue(
      new StreamTransportError("not found", { status: 404 }),
    );
    const unarySpy = vi
      .spyOn(api, "explain")
      .mockResolvedValue({
        answer: "Recovery restores HP outside combat using deprivations.",
        thinking: "",
      });

    const consumed = await game.submit("/explain how does recovery work?");

    expect(consumed).toBe(true);
    expect(unarySpy).toHaveBeenCalledTimes(1);
    const oocNote = game.notes.find((n) => n.kind === "explanation");
    expect(oocNote?.text).toContain("Recovery restores HP");
    expect(oocNote?.question).toBe("how does recovery work?");
  });

  it("surfaces a slash error and does not dispatch when /explain has no body", async () => {
    // Empty-body errors land as a client-only note with the parser's
    // hint text so the player sees what's missing without us shipping
    // a request the backend's `min_length=1` validator would reject.
    const streamSpy = vi.spyOn(api, "streamExplain");
    const unarySpy = vi.spyOn(api, "explain");

    const consumed = await game.submit("/explain");

    expect(consumed).toBe(true);
    expect(streamSpy).not.toHaveBeenCalled();
    expect(unarySpy).not.toHaveBeenCalled();
    expect(
      game.notes.some((n) => n.kind === "error" && n.text.includes("/explain")),
    ).toBe(true);
  });

  it("surfaces server-aborted setup streams as an error instead of silent null", async () => {
    vi.spyOn(api, "streamCharacterQuiz").mockResolvedValue({
      kind: "aborted",
      reason: "server",
    } as never);
    vi.spyOn(api, "generateCharacterQuiz").mockResolvedValue({
      quiz: {
        concept: "unused",
        questions: [],
      },
      thinking: "",
    } as never);

    const result = await game.generateCharacterQuiz("A scarred deserter.");

    expect(result).toBeNull();
    expect(game.error).toBe("The request ended before a final result arrived.");
    expect(game.isLoading).toBe(false);
  });

  it("threads backend stage frames into the streaming.stages checklist in pipeline order, including a late post-prose stage", async () => {
    // The backend emits an ordered `stage` bootstrap at stream open
    // (one frame per pipeline step, status `pending` or `skipped`) and
    // then flips each step to `active` and `done` as it works
    // through them. The store must:
    //   - keep the bootstrap order stable as `order` indices,
    //   - update an existing stage in place (not append a duplicate)
    //     when a later frame flips its status,
    //   - preserve a new stage appended after prose has already started,
    //   - clear the checklist when the stream finishes.
    const previousState: NonNullable<typeof game.state> = {
      id: "state_pre",
      oracle_history: [],
    } as never;
    const finalState: NonNullable<typeof game.state> = {
      id: "state_post",
      oracle_history: [],
    } as never;
    game.state = previousState;

    let observedDuringStream: ReturnType<typeof getStages> | null = null;
    function getStages() {
      // Snapshot is a shallow copy keyed by stage_id so the assertion
      // doesn't race the store's own array-replace semantics. We
      // sort by `order` because the checklist UI also sorts by it.
      return game.streaming.stages
        .slice()
        .sort((a, b) => a.order - b.order)
        .map((s) => ({ id: s.stageId, status: s.status, order: s.order }));
    }

    vi.spyOn(api, "streamSubmitTurn").mockImplementation(
      (_text, handlers) => {
        handlers.onMeta?.({ type: "meta", request_id: "req_1", route: "player_action" });
        handlers.onStage?.({
          type: "stage",
          stage_id: "planning_turn",
          label: "Planning turn",
          status: "pending",
        });
        handlers.onStage?.({
          type: "stage",
          stage_id: "preparing_narration",
          label: "Preparing narration",
          status: "pending",
        });
        handlers.onStage?.({
          type: "stage",
          stage_id: "streaming_narration",
          label: "Streaming narration",
          status: "pending",
        });
        handlers.onStage?.({
          type: "stage",
          stage_id: "planning_turn",
          label: "Planning turn",
          status: "active",
        });
        handlers.onStage?.({
          type: "stage",
          stage_id: "planning_turn",
          label: "Planning turn",
          status: "done",
        });
        handlers.onStage?.({
          type: "stage",
          stage_id: "preparing_narration",
          label: "Preparing narration",
          status: "active",
        });
        handlers.onContentDelta?.({ type: "content_delta", text: "Ash falls." });
        handlers.onStage?.({
          type: "stage",
          stage_id: "reconciling_continuity",
          label: "Reconciling continuity",
          status: "active",
        });
        // Snapshot mid-stream so we can assert in-place updates and
        // stable ordering before the stream completes, including a
        // stage that arrived after prose was already flowing.
        observedDuringStream = getStages();
        handlers.onFinalState?.({ type: "final_state", state: finalState, thinking: null });
        return Promise.resolve({ kind: "final", final: { type: "final_state", state: finalState, thinking: null } } as never);
      },
    );

    await game.submitTurn("I peer into the dark.");

    expect(observedDuringStream).not.toBeNull();
    // Order is the bootstrap order; stages added later were appended.
    expect(observedDuringStream!.map((s) => s.id)).toEqual([
      "planning_turn",
      "preparing_narration",
      "streaming_narration",
      "reconciling_continuity",
    ]);
    // In-place updates kept the same `order` index for planning_turn
    // even after two status flips (active, done), while the late
    // post-prose stage appended at the tail.
    expect(observedDuringStream!.map((s) => s.order)).toEqual([0, 1, 2, 3]);
    expect(observedDuringStream!.map((s) => s.status)).toEqual([
      "done",
      "active",
      "pending",
      "active",
    ]);
    // The store always clears the streaming buffer at end-of-flight so
    // the checklist doesn't linger on the next idle composer state.
    expect(game.streaming.stages).toEqual([]);
    expect(game.streaming.active).toBe(false);
  });

  it("clears streaming.stages when the player cancels a streamed request mid-flight", async () => {
    // Cancel must collapse the in-flight checklist immediately so the
    // chat surface doesn't show a stale "active" pulse for whichever
    // step the backend was in when we tore the connection down. We
    // drive a real streamed turn that hangs after emitting a few
    // stage frames, then call cancelCurrentRequest from a microtask
    // and assert the stages array is empty after the call resolves.
    vi.spyOn(api, "cancelRequest").mockResolvedValue(undefined as never);
    vi.spyOn(api, "streamSubmitTurn").mockImplementation(
      (_text, handlers, signal) => {
        handlers.onMeta?.({ type: "meta", request_id: "req_42", route: "player_action" });
        handlers.onStage?.({
          type: "stage",
          stage_id: "planning_turn",
          label: "Planning turn",
          status: "active",
        });
        // Trigger cancel from the same tick so the abort is observed
        // before the next handler call would land. The promise the
        // store awaits resolves with `kind: "aborted"` once the
        // signal trips.
        queueMicrotask(() => game.cancelCurrentRequest());
        return new Promise((resolve) => {
          signal?.addEventListener("abort", () => {
            resolve({ kind: "aborted", reason: "client" } as never);
          });
        });
      },
    );

    await game.submitTurn("I look around.");

    expect(game.streaming.stages).toEqual([]);
    expect(game.streaming.active).toBe(false);
    expect(game.isLoading).toBe(false);
  });

  it("updateDirectives forwards both fields to the directives endpoint and adopts the echoed state", async () => {
    // B-02: directives are a separate state surface from
    // setting_notes / player_notes. The store action must hit
    // `api.updateDirectives` (not `updateNotes`) and then adopt
    // whatever the backend echoes back as the new canonical
    // state — empty strings included, since "clear my guidance"
    // is a legal commit.
    const updateSpy = vi
      .spyOn(api, "updateDirectives")
      .mockResolvedValue({
        id: "state_after",
        directives: {
          world_guidance: "Miracles are subtle.",
          play_guidance: "End scenes on a question.",
        },
      } as never);
    const notesSpy = vi.spyOn(api, "updateNotes");

    await game.updateDirectives(
      "Miracles are subtle.",
      "End scenes on a question.",
    );

    expect(notesSpy).not.toHaveBeenCalled();
    expect(updateSpy).toHaveBeenCalledTimes(1);
    const [worldArg, playArg] = updateSpy.mock.calls[0]!;
    expect(worldArg).toBe("Miracles are subtle.");
    expect(playArg).toBe("End scenes on a question.");

    // The echoed state replaces `state` wholesale via #run, so the
    // next render sees the new directives without a manual merge.
    expect(game.state?.id).toBe("state_after");
    expect(game.state?.directives.world_guidance).toBe("Miracles are subtle.");
    expect(game.state?.directives.play_guidance).toBe("End scenes on a question.");
  });
});
