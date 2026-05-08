import { describe, expect, it, vi } from "vitest";

import {
  consumeStream,
  StreamTransportError,
  type StreamHandlers,
} from "./streaming";
import type { StreamEvent } from "./streaming-types";

// We exercise the parser by stubbing fetch with a Response whose body
// is a ReadableStream we author byte-by-byte. Why byte-by-byte and not
// "one chunk per event":
//   the boundary-spanning behavior — a JSON object split across two
//   chunks — is exactly the kind of bug NDJSON parsers regress on, and
//   it would silently pass a coarser test that hands the parser one
//   complete object per chunk.

function streamFromChunks(chunks: readonly string[], headers?: Record<string, string>): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "application/x-ndjson", ...(headers ?? {}) },
  });
}

function recordingHandlers(): {
  events: StreamEvent[];
  handlers: StreamHandlers;
} {
  const events: StreamEvent[] = [];
  return {
    events,
    handlers: {
      onAny: (event) => events.push(event),
    },
  };
}

describe("consumeStream", () => {
  it("dispatches every newline-delimited event in order", async () => {
    const lines = [
      JSON.stringify({ type: "meta", request_id: "req_1", route: "player_action" }),
      JSON.stringify({ type: "content_delta", text: "The wind " }),
      JSON.stringify({ type: "content_delta", text: "carries ash." }),
      JSON.stringify({
        type: "final_state",
        state: { id: "g1" },
        thinking: null,
      }),
    ];
    const fetchMock = vi.fn().mockResolvedValue(streamFromChunks([lines.join("\n") + "\n"]));
    vi.stubGlobal("fetch", fetchMock);

    const { events, handlers } = recordingHandlers();
    const result = await consumeStream("/api/turn/stream", handlers, {
      json: { text: "I look around" },
    });

    vi.unstubAllGlobals();
    expect(events).toHaveLength(4);
    expect(events[0]?.type).toBe("meta");
    expect(events[1]?.type).toBe("content_delta");
    expect(events[3]?.type).toBe("final_state");
    expect(result.kind).toBe("final");
  });

  it("rebuilds JSON objects split across read() chunks", async () => {
    const meta = JSON.stringify({ type: "meta", request_id: "r", route: "yes_no" });
    const delta = JSON.stringify({ type: "content_delta", text: "ok" });
    // Split the second event in the middle of its JSON. The parser
    // should hold the partial line in its buffer and only emit when
    // the trailing newline arrives in a later chunk.
    const cut = Math.floor(delta.length / 2);
    const chunks = [
      `${meta}\n${delta.slice(0, cut)}`,
      `${delta.slice(cut)}\n`,
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamFromChunks(chunks)));

    const { events, handlers } = recordingHandlers();
    await consumeStream("/api/turn/stream", handlers);

    vi.unstubAllGlobals();
    expect(events.map((e) => e.type)).toEqual(["meta", "content_delta"]);
    expect((events[1] as Extract<StreamEvent, { type: "content_delta" }>).text).toBe("ok");
  });

  it("flushes a trailing line that has no terminating newline", async () => {
    const meta = JSON.stringify({ type: "meta", request_id: "r", route: "yes_no" });
    const final = JSON.stringify({ type: "final_state", state: { id: "g" }, thinking: null });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(streamFromChunks([`${meta}\n${final}`])),
    );

    const { events, handlers } = recordingHandlers();
    const result = await consumeStream("/api/turn/stream", handlers);

    vi.unstubAllGlobals();
    expect(events.map((e) => e.type)).toEqual(["meta", "final_state"]);
    expect(result.kind).toBe("final");
  });

  it("returns kind: 'aborted' with reason 'server' when the stream ends without a final event", async () => {
    const meta = JSON.stringify({ type: "meta", request_id: "r", route: "yes_no" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamFromChunks([`${meta}\n`])));

    const result = await consumeStream("/api/turn/stream", { onAny: () => {} });

    vi.unstubAllGlobals();
    expect(result.kind).toBe("aborted");
    if (result.kind === "aborted") expect(result.reason).toBe("server");
  });

  it("returns kind: 'error' when the stream emits an error event", async () => {
    const lines = [
      JSON.stringify({ type: "meta", request_id: "r", route: "yes_no" }),
      JSON.stringify({ type: "error", message: "model timed out", code: "timeout", state: null }),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(streamFromChunks([lines.join("\n") + "\n"])),
    );

    const result = await consumeStream("/api/turn/stream", { onAny: () => {} });

    vi.unstubAllGlobals();
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.event.message).toBe("model timed out");
  });

  it("throws StreamTransportError with status on non-2xx responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("Not Found", { status: 404, headers: { "Content-Type": "text/plain" } }),
      ),
    );

    await expect(
      consumeStream("/api/turn/stream", { onAny: () => {} }),
    ).rejects.toBeInstanceOf(StreamTransportError);

    try {
      await consumeStream("/api/turn/stream", { onAny: () => {} });
      throw new Error("expected throw");
    } catch (exc) {
      expect(exc).toBeInstanceOf(StreamTransportError);
      expect((exc as StreamTransportError).status).toBe(404);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("throws StreamTransportError on malformed JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(streamFromChunks(["{not_json}\n"])),
    );

    await expect(
      consumeStream("/api/turn/stream", { onAny: () => {} }),
    ).rejects.toBeInstanceOf(StreamTransportError);
    vi.unstubAllGlobals();
  });

  it("returns kind: 'aborted' with reason 'client' when fetch itself is aborted", async () => {
    // Simulate fetch rejecting with AbortError when the signal fires.
    // We don't need to drive the stream body — the abort should be
    // detected at the fetch level and result in the same `client`
    // aborted result the runtime would produce.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
        return new Promise((_resolve, reject) => {
          if (init?.signal?.aborted) {
            reject(new DOMException("Aborted", "AbortError"));
            return;
          }
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        });
      }),
    );

    const controller = new AbortController();
    queueMicrotask(() => controller.abort());
    const result = await consumeStream(
      "/api/turn/stream",
      { onAny: () => {} },
      { signal: controller.signal },
    );

    vi.unstubAllGlobals();
    expect(result.kind).toBe("aborted");
    if (result.kind === "aborted") expect(result.reason).toBe("client");
  });

  it("returns kind: 'aborted' with reason 'client' when read() is aborted mid-stream", async () => {
    // Author a stream that errors with AbortError when the signal
    // fires, simulating the runtime tearing the body down.
    let errorCallback: ((reason: unknown) => void) | null = null;
    const body = new ReadableStream<Uint8Array>({
      start(streamController) {
        errorCallback = (reason) => streamController.error(reason);
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
        init?.signal?.addEventListener("abort", () => {
          errorCallback?.(new DOMException("Aborted", "AbortError"));
        });
        return Promise.resolve(
          new Response(body, {
            status: 200,
            headers: { "Content-Type": "application/x-ndjson" },
          }),
        );
      }),
    );

    const controller = new AbortController();
    queueMicrotask(() => controller.abort());
    const result = await consumeStream(
      "/api/turn/stream",
      { onAny: () => {} },
      { signal: controller.signal },
    );

    vi.unstubAllGlobals();
    expect(result.kind).toBe("aborted");
    if (result.kind === "aborted") expect(result.reason).toBe("client");
  });

  it("invokes typed handlers in addition to onAny", async () => {
    const events = [
      { type: "meta", request_id: "r", route: "yes_no" },
      { type: "thinking_delta", text: "considering" },
      { type: "content_delta", text: "yes." },
      { type: "final_state", state: { id: "g" }, thinking: "considering" },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamFromChunks([events.map((e) => JSON.stringify(e)).join("\n") + "\n"]),
      ),
    );

    const calls: string[] = [];
    await consumeStream("/api/turn/stream", {
      onMeta: () => calls.push("meta"),
      onThinkingDelta: () => calls.push("thinking"),
      onContentDelta: () => calls.push("content"),
      onFinalState: () => calls.push("final"),
    });

    vi.unstubAllGlobals();
    expect(calls).toEqual(["meta", "thinking", "content", "final"]);
  });

  it("dispatches stage events through onStage in pipeline order, including late stages after prose starts", async () => {
    // The backend bootstraps a `stage` frame for each pipeline step
    // at stream open (status=pending or skipped) and then flips each
    // step to active/done as it works through them. A later
    // reconciliation step may arrive after content_delta has already
    // started streaming; the transport still has to preserve wire
    // order so the checklist UI can mirror the real pipeline.
    const lines = [
      JSON.stringify({ type: "meta", request_id: "r", route: "player_action" }),
      JSON.stringify({ type: "stage", stage_id: "planning_turn", label: "Planning turn", status: "skipped" }),
      JSON.stringify({ type: "stage", stage_id: "preparing_narration", label: "Preparing narration", status: "pending" }),
      JSON.stringify({ type: "stage", stage_id: "preparing_narration", label: "Preparing narration", status: "active" }),
      JSON.stringify({ type: "stage", stage_id: "preparing_narration", label: "Preparing narration", status: "done" }),
      JSON.stringify({ type: "content_delta", text: "Ash falls." }),
      JSON.stringify({ type: "stage", stage_id: "reconciling_continuity", label: "Reconciling continuity", status: "active" }),
      JSON.stringify({ type: "stage", stage_id: "reconciling_continuity", label: "Reconciling continuity", status: "done" }),
      JSON.stringify({ type: "final_state", state: { id: "g" }, thinking: null }),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(streamFromChunks([lines.join("\n") + "\n"])),
    );

    const stageCalls: Array<{ stage_id: string; status: string }> = [];
    const result = await consumeStream("/api/turn/stream", {
      onStage: (event) => stageCalls.push({ stage_id: event.stage_id, status: event.status }),
    });
    vi.unstubAllGlobals();

    expect(result.kind).toBe("final");
    expect(stageCalls).toEqual([
      { stage_id: "planning_turn", status: "skipped" },
      { stage_id: "preparing_narration", status: "pending" },
      { stage_id: "preparing_narration", status: "active" },
      { stage_id: "preparing_narration", status: "done" },
      { stage_id: "reconciling_continuity", status: "active" },
      { stage_id: "reconciling_continuity", status: "done" },
    ]);
  });
});
