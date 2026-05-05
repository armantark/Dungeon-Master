import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";

// Why a dedicated test file rather than appending to streaming.test.ts:
//   The cancel POST is its own contract — the URL shape (path-encoded
//   request_id) and the discard-only payload semantics. Mixing it into
//   streaming.test.ts would conflate the two assertions and force
//   future contributors to scroll a thousand-line file to find either.
//
// The store's `cancelCurrentRequest` is fire-and-forget by design (see
// the comment in store.svelte.ts), so we test the api layer directly
// rather than driving it through a Svelte-runes harness. The store's
// UI behavior is covered by manual testing per the project rules.

describe("api.cancelRequest", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs to /api/requests/{id}/cancel and returns the cancelled flag", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ cancelled: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.cancelRequest("req_abc123");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/requests/req_abc123/cancel");
    expect((init as RequestInit).method).toBe("POST");
    expect(result).toEqual({ cancelled: true });
  });

  it("path-encodes request ids that contain URL-unsafe characters", async () => {
    // The backend mints opaque ids from `uuid4().hex`, so in practice
    // we'll only ever see [a-f0-9_]. We still encode to insulate the
    // call site against the day someone stuffs a slash or a space into
    // the id (e.g. for testing) — failing closed at the URL layer is
    // cheaper than a 404 from FastAPI's path matcher.
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ cancelled: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.cancelRequest("req with/slash");

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/requests/req%20with%2Fslash/cancel");
  });

  it("returns {cancelled: false} when the backend reports a stale request id", async () => {
    // The backend's contract is that an unknown / already-finished
    // request id resolves with `cancelled: false` rather than a 404,
    // so the call site never has to distinguish "race won, request
    // already done" from "id wrong, your bug." The api wrapper must
    // pass that boolean through verbatim.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ cancelled: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const result = await api.cancelRequest("req_already_done");
    expect(result).toEqual({ cancelled: false });
  });
});
