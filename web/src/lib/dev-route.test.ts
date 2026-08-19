import { describe, expect, it } from "vitest";

import { ARCHITECTURE_PATH, shouldMountArchitecture } from "./dev-route";

describe("shouldMountArchitecture", () => {
  it("mounts only on the exact enabled development path", () => {
    expect(shouldMountArchitecture(ARCHITECTURE_PATH, true, true)).toBe(true);
    expect(shouldMountArchitecture(`${ARCHITECTURE_PATH}/`, true, true)).toBe(true);
  });

  it("keeps the normal app when the flag is absent", () => {
    expect(shouldMountArchitecture(ARCHITECTURE_PATH, true, false)).toBe(false);
  });

  it("keeps the normal app on every other path", () => {
    expect(shouldMountArchitecture("/", true, true)).toBe(false);
    expect(shouldMountArchitecture("/dev/architecture", true, true)).toBe(false);
  });

  it("never exposes the map in a production build", () => {
    expect(shouldMountArchitecture(ARCHITECTURE_PATH, false, true)).toBe(false);
  });
});
