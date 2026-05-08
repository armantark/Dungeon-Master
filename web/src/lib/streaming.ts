// NDJSON streaming transport for model-authored backend endpoints.
//
// Why NDJSON over text/event-stream:
// - Every model-authored endpoint we stream is a POST with a JSON body
//   (concept, action text, regen target id, ...). EventSource is GET-only,
//   so we'd need a fetch+ReadableStream parser anyway. Once we're parsing
//   manually, NDJSON is simpler than SSE: one JSON object per `\n`, no
//   `event:` / `data:` framing, no `id:` resume hints we don't use, and
//   no comment lines to filter.
// - The chosen contract is: `Content-Type: application/x-ndjson`, each
//   line is a discriminated union with a `type` field. Backend-frontend
//   alignment is enforced at the type level via `StreamEvent` in
//   ./streaming-types so a misnamed event surfaces in tsc, not at runtime.
//
// Why a generic `consumeStream` over per-endpoint code:
// - Every streamed endpoint follows the same lifecycle: open, drain
//   deltas, reconcile a final payload, close. Inlining that loop into
//   each api method bloats the call sites and forks the cancel/error
//   semantics. The handler-callbacks pattern keeps one transport and
//   five small per-call dispatchers.

import type { StreamEvent } from "./streaming-types";

// Anything the runtime can throw at us during a stream read. We keep the
// type narrow so callers only have to handle three branches: an aborted
// stream, a transport error (network/HTTP/parse), and an explicit error
// event from the backend. The `code` field on TransportError is set when
// we can extract one (HTTP status, parse failure marker); otherwise null.
export class StreamTransportError extends Error {
  public readonly code: string | null;
  public readonly status: number | null;
  public readonly detail: unknown;

  constructor(message: string, opts?: {
    code?: string | null;
    status?: number | null;
    detail?: unknown;
  }) {
    super(message);
    this.name = "StreamTransportError";
    this.code = opts?.code ?? null;
    this.status = opts?.status ?? null;
    this.detail = opts?.detail;
  }
}

// A handler bag is the per-event-type callback set the caller wires up.
// Every handler is optional because real endpoints emit a different
// subset (e.g. character/quiz never emits `oracle_outcome`). Unknown
// event types are silently ignored — we want adding a new event on the
// backend to be backwards-compatible until the frontend catches up.
export interface StreamHandlers {
  onMeta?: (event: Extract<StreamEvent, { type: "meta" }>) => void;
  // Backend pipeline progress. Bootstrap frames arrive in pipeline
  // order at stream start (each pending or skipped) and the active/done
  // frames follow as the backend works through them. Some stages may
  // happen after prose starts streaming but before the terminal
  // `final_state` / `final_payload`.
  onStage?: (event: Extract<StreamEvent, { type: "stage" }>) => void;
  onMechanics?: (event: Extract<StreamEvent, { type: "mechanics_ready" }>) => void;
  onOracleOutcome?: (event: Extract<StreamEvent, { type: "oracle_outcome" }>) => void;
  onThinkingDelta?: (event: Extract<StreamEvent, { type: "thinking_delta" }>) => void;
  onContentDelta?: (event: Extract<StreamEvent, { type: "content_delta" }>) => void;
  onFinalState?: (event: Extract<StreamEvent, { type: "final_state" }>) => void;
  onFinalPayload?: (event: Extract<StreamEvent, { type: "final_payload" }>) => void;
  onError?: (event: Extract<StreamEvent, { type: "error" }>) => void;
  // Catch-all hook so callers can log/inspect unknown events without
  // forcing them through the typed channels. Returns nothing on purpose:
  // the dispatcher already invokes the typed handler when one matches.
  onAny?: (event: StreamEvent) => void;
}

export interface StreamCallOptions {
  signal?: AbortSignal;
  // HTTP method. Defaults to POST because every "open a fresh
  // stream" route is a POST with a JSON body. The GET path exists
  // exclusively for the reattach endpoint
  // (`GET /api/requests/{id}/stream`), which the backend exposes as
  // a body-less re-subscribe and rejects when called with anything
  // else. Keeping the default POST means none of the existing call
  // sites have to know this option exists.
  method?: "GET" | "POST";
  // Send body as JSON. Mutually exclusive with `body`.
  json?: unknown;
  // Raw body. Set Content-Type yourself if you use this.
  body?: BodyInit;
  // Extra headers (we always set Accept: application/x-ndjson).
  headers?: HeadersInit;
}

// A typed Result so callers don't have to thread Promise<void> + a side
// channel for "did the stream end with `final_state` or with `error`?".
// `kind === "final"` means we received exactly one final_* event before
// EOF and the union narrows to it. `kind === "aborted"` covers both
// AbortController cancel and stream cancellation; `kind === "error"`
// means the backend explicitly emitted an error event (not a transport
// failure — that throws).
export type StreamResult<TFinal extends StreamEvent = StreamEvent> =
  | { kind: "final"; final: Extract<TFinal, { type: "final_state" | "final_payload" }> }
  | { kind: "aborted"; reason: "client" | "server" }
  | { kind: "error"; event: Extract<StreamEvent, { type: "error" }> };

// Consume an NDJSON stream from a POST endpoint and dispatch every event
// through the supplied handlers. Returns a `StreamResult` so the caller
// knows whether the stream concluded cleanly. Transport-level failures
// (network, non-2xx, malformed JSON) raise `StreamTransportError`;
// backend-level failures (an `error` event in the stream) resolve with
// `kind: "error"` so the call site can branch on them deterministically.
export async function consumeStream<TFinal extends StreamEvent = StreamEvent>(
  path: string,
  handlers: StreamHandlers,
  options: StreamCallOptions = {},
): Promise<StreamResult<TFinal>> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/x-ndjson");
  let body: BodyInit | undefined = options.body;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }

  const method = options.method ?? "POST";
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      // GETs MUST NOT carry a body; some browsers tolerate it but
      // fetch() will reject with a TypeError on Safari. We let any
      // accidental `json`/`body` option fall through to undefined
      // for GET requests so the call site doesn't have to remember.
      body: method === "GET" ? undefined : body,
      signal: options.signal,
    });
  } catch (exc) {
    if (isAbortError(exc)) {
      return { kind: "aborted", reason: "client" };
    }
    throw new StreamTransportError(
      exc instanceof Error ? exc.message : "Network error",
      { detail: exc },
    );
  }

  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = await response.json();
    } catch {
      // ignore — the status text is the best we have
    }
    throw new StreamTransportError(
      typeof detail === "string" ? detail : `Stream request failed (${response.status})`,
      { status: response.status, detail },
    );
  }

  if (response.body === null) {
    throw new StreamTransportError("Stream response had no body", {
      status: response.status,
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalEvent: Extract<StreamEvent, { type: "final_state" | "final_payload" }> | null = null;
  let errorEvent: Extract<StreamEvent, { type: "error" }> | null = null;

  try {
    // We loop until the reader signals EOF. We deliberately don't
    // chunk-split inside `read()` because the WHATWG ReadableStream
    // already hands us boundary-aware Uint8Array chunks; our only job
    // is to assemble newline-delimited JSON across those chunks.
    for (;;) {
      let read: ReadableStreamReadResult<Uint8Array>;
      try {
        read = await reader.read();
      } catch (exc) {
        if (isAbortError(exc)) {
          return { kind: "aborted", reason: "client" };
        }
        throw new StreamTransportError(
          exc instanceof Error ? exc.message : "Stream read failed",
          { detail: exc },
        );
      }

      if (read.done) break;

      buffer += decoder.decode(read.value, { stream: true });

      // Emit every complete line in the buffer; keep the trailing
      // partial line (no terminating \n yet) for the next iteration.
      let newlineIndex = buffer.indexOf("\n");
      while (newlineIndex !== -1) {
        const line = buffer.slice(0, newlineIndex);
        buffer = buffer.slice(newlineIndex + 1);
        const trimmed = line.trim();
        if (trimmed !== "") {
          const event = parseLine(trimmed);
          dispatch(event, handlers);
          if (event.type === "final_state" || event.type === "final_payload") {
            finalEvent = event;
          } else if (event.type === "error") {
            errorEvent = event;
          }
        }
        newlineIndex = buffer.indexOf("\n");
      }
    }

    // Flush a trailing line that wasn't newline-terminated. Some servers
    // forget the final \n; we still want to honor whatever final event
    // they emitted rather than dropping it on the floor.
    const tail = buffer.trim();
    if (tail !== "") {
      const event = parseLine(tail);
      dispatch(event, handlers);
      if (event.type === "final_state" || event.type === "final_payload") {
        finalEvent = event;
      } else if (event.type === "error") {
        errorEvent = event;
      }
    }
  } finally {
    // Releasing the lock lets callers re-issue requests without leaking
    // the underlying socket on cancel paths. We don't `cancel()` because
    // EOF means the body is already drained; cancel() would be a no-op
    // but adds a thrown rejection on some browsers.
    try {
      reader.releaseLock();
    } catch {
      // ignore — releaseLock can throw if the stream is already locked
      // by the runtime when the request was aborted mid-read.
    }
  }

  if (errorEvent !== null) {
    return { kind: "error", event: errorEvent };
  }
  if (finalEvent !== null) {
    return { kind: "final", final: finalEvent as Extract<TFinal, { type: "final_state" | "final_payload" }> };
  }
  // Backend closed the stream without a final event. Treat as a server-
  // side abort so the caller can show a "stream ended unexpectedly"
  // hint without throwing — this happens, for example, when the LLM
  // upstream times out and the backend bails after deltas.
  return { kind: "aborted", reason: "server" };
}

function dispatch(event: StreamEvent, handlers: StreamHandlers): void {
  handlers.onAny?.(event);
  switch (event.type) {
    case "meta":
      handlers.onMeta?.(event);
      return;
    case "stage":
      handlers.onStage?.(event);
      return;
    case "mechanics_ready":
      handlers.onMechanics?.(event);
      return;
    case "oracle_outcome":
      handlers.onOracleOutcome?.(event);
      return;
    case "thinking_delta":
      handlers.onThinkingDelta?.(event);
      return;
    case "content_delta":
      handlers.onContentDelta?.(event);
      return;
    case "final_state":
      handlers.onFinalState?.(event);
      return;
    case "final_payload":
      handlers.onFinalPayload?.(event);
      return;
    case "error":
      handlers.onError?.(event);
      return;
  }
}

function parseLine(line: string): StreamEvent {
  let raw: unknown;
  try {
    raw = JSON.parse(line);
  } catch (exc) {
    throw new StreamTransportError(
      `Malformed NDJSON line: ${exc instanceof Error ? exc.message : "unknown"}`,
      { code: "parse_error", detail: line },
    );
  }
  if (raw === null || typeof raw !== "object") {
    throw new StreamTransportError("Stream event was not a JSON object", {
      code: "parse_error",
      detail: raw,
    });
  }
  // Validate the discriminator at runtime; the type union guarantees at
  // compile time that every known `type` has a typed handler, but the
  // network can still hand us arbitrary text.
  const event = raw as { type?: unknown };
  if (typeof event.type !== "string") {
    throw new StreamTransportError("Stream event missing 'type' discriminator", {
      code: "parse_error",
      detail: raw,
    });
  }
  return raw as StreamEvent;
}

function isAbortError(exc: unknown): boolean {
  return exc instanceof DOMException && exc.name === "AbortError";
}
