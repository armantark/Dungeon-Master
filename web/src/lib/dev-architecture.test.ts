import { describe, expect, it } from "vitest";

import {
  ARCHITECTURE_NODES,
  ARCHITECTURE_PATHS,
  frontDepth,
  nodeById,
  nodesInPainterOrder,
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

  it("sorts building groups by their projected front edge", () => {
    const painted = nodesInPainterOrder(ARCHITECTURE_NODES);
    for (let index = 1; index < painted.length; index += 1) {
      const previous = painted[index - 1];
      const current = painted[index];
      expect(previous).toBeDefined();
      expect(current).toBeDefined();
      expect(frontDepth(previous!), `${previous!.id} before ${current!.id}`).toBeLessThanOrEqual(
        frontDepth(current!),
      );
    }
  });

  it("keeps frontend, backend, persistence, and delivery roles represented", () => {
    const roles = new Set(ARCHITECTURE_NODES.map((node) => node.role));
    expect(roles).toEqual(
      new Set(["client", "python", "structured", "prose", "persist", "desktop"]),
    );
  });
});
