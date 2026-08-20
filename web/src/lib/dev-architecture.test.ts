import { describe, expect, it } from "vitest";

import {
  ARCHITECTURE_NODES,
  ARCHITECTURE_PATHS,
  nodeById,
  routeSegmentAt,
} from "./dev-architecture";

describe("architecture map contracts", () => {
  it("keeps every path connected to real nodes", () => {
    for (const path of ARCHITECTURE_PATHS) {
      expect(path.steps.length).toBeGreaterThan(2);
      for (const step of path.steps) {
        expect(nodeById(step.node), `${path.id}:${step.node}`).toBeDefined();
      }
    }
  });

  it("keeps one distinct building kind for every infrastructure node", () => {
    expect(ARCHITECTURE_NODES).toHaveLength(15);
    expect(new Set(ARCHITECTURE_NODES.map((node) => node.kind)).size).toBe(15);
  });

  it("keeps frontend, backend, persistence, and delivery roles represented", () => {
    const roles = new Set(ARCHITECTURE_NODES.map((node) => node.role));
    expect(roles).toEqual(
      new Set(["client", "python", "structured", "prose", "persist", "desktop"]),
    );
  });

  it("reveals no connector before the second route node", () => {
    const path = ARCHITECTURE_PATHS[0]!;
    expect(routeSegmentAt(path, -1)).toBeUndefined();
    expect(routeSegmentAt(path, 0)).toBeUndefined();
    expect(routeSegmentAt(path, path.steps.length)).toBeUndefined();
  });

  it("reveals exactly the connector at the trace cursor", () => {
    const path = ARCHITECTURE_PATHS[0]!;
    expect(routeSegmentAt(path, 1)).toEqual({
      from: path.steps[0],
      to: path.steps[1],
    });
    expect(routeSegmentAt(path, 2)).toEqual({
      from: path.steps[1],
      to: path.steps[2],
    });
  });
});
