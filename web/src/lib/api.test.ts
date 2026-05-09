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
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "ok" }),
    });
    vi.stubGlobal("fetch", fetchSpy);
    setApiBase("http://127.0.0.1:8123/api/");

    await api.health();

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8123/api/health",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });
});
