import { afterEach, describe, expect, it, vi } from "vitest";

import { api, getApiBase, setApiBase } from "./api";

describe("api base resolver", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setApiBase("/api");
  });

  it("defaults to the relative /api base", () => {
    expect(getApiBase()).toBe("/api");
  });

  it("retargets requests when a runtime base is injected", async () => {
    const fetchSpy = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    setApiBase("http://127.0.0.1:8123/api/");

    await api.health();

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const call = fetchSpy.mock.calls[0];
    expect(call?.[0]).toBe("http://127.0.0.1:8123/api/health");
    expect(call?.[1]?.headers).toBeInstanceOf(Headers);
  });
});
