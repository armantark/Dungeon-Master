import { describe, expect, it } from "vitest";

import { ARCHITECTURE_NODES, ARCHITECTURE_PATHS } from "./dev-architecture";
import {
  PLACEMENTS,
  ZONES,
  placementOf,
  radiusOf,
  routeLines,
  screenDepth,
  type RoutePoint,
} from "./architecture-layout";
import { placeLabels, type LabelCandidate } from "./architecture-labels";

/** Distance from a plot centre to the nearest point of one route run. */
function distanceToRun(point: RoutePoint, from: RoutePoint, to: RoutePoint): number {
  const runX = to.x - from.x;
  const runZ = to.z - from.z;
  const length = runX * runX + runZ * runZ;
  const travel =
    length === 0
      ? 0
      : Math.max(
          0,
          Math.min(1, ((point.x - from.x) * runX + (point.z - from.z) * runZ) / length),
        );
  return Math.hypot(point.x - (from.x + runX * travel), point.z - (from.z + runZ * travel));
}

describe("architecture plan layout", () => {
  it("gives every component exactly one plot and one code", () => {
    expect(PLACEMENTS).toHaveLength(ARCHITECTURE_NODES.length);
    expect(new Set(PLACEMENTS.map((placement) => placement.id)).size).toBe(
      ARCHITECTURE_NODES.length,
    );
    expect(new Set(PLACEMENTS.map((placement) => placement.code)).size).toBe(
      ARCHITECTURE_NODES.length,
    );
  });

  it("leaves a street's width between neighbours on the same street", () => {
    for (const a of PLACEMENTS) {
      for (const b of PLACEMENTS) {
        if (a === b || a.z !== b.z) continue;
        const clearance = Math.abs(a.x - b.x) - radiusOf(a.node) - radiusOf(b.node);
        expect(clearance, `${a.id} vs ${b.id}`).toBeGreaterThan(1.2);
      }
    }
  });

  it("keeps separate streets from touching in depth", () => {
    for (const a of PLACEMENTS) {
      for (const b of PLACEMENTS) {
        if (a.z === b.z) continue;
        const clearance = Math.abs(a.z - b.z) - radiusOf(a.node) - radiusOf(b.node);
        expect(clearance, `${a.id} vs ${b.id}`).toBeGreaterThan(1.5);
      }
    }
  });

  it("keeps every building inside its own plate", () => {
    for (const placement of PLACEMENTS) {
      const zone = ZONES.find((candidate) => candidate.id === placement.zone);
      expect(zone, placement.id).toBeDefined();
      const [minX, maxX, minZ, maxZ] = zone!.bounds;
      const radius = radiusOf(placement.node);
      expect(placement.x - radius, placement.id).toBeGreaterThan(minX);
      expect(placement.x + radius, placement.id).toBeLessThan(maxX);
      expect(placement.z - radius, placement.id).toBeGreaterThan(minZ);
      expect(placement.z + radius, placement.id).toBeLessThan(maxZ);
    }
  });

  it("reads the sections top to bottom in their numbered order", () => {
    for (let index = 1; index < ZONES.length; index += 1) {
      const previous = ZONES[index - 1]!;
      const zone = ZONES[index]!;
      expect(zone.index).toBe(previous.index + 1);
      expect(zone.bounds[2], zone.id).toBeGreaterThan(previous.bounds[3]);
      expect(
        screenDepth(zone.bounds[2], zone.elevation),
        zone.id,
      ).toBeGreaterThan(screenDepth(previous.bounds[3], previous.elevation));
    }
  });

  it("gives every section a hatch no other section uses", () => {
    const prints = ZONES.map((zone) => `${zone.hatch.angles.join(",")}@${zone.hatch.spacing}`);
    expect(new Set(prints).size).toBe(ZONES.length);
  });
});

describe("architecture route lines", () => {
  const paths = ARCHITECTURE_PATHS.map((path) => ({
    path,
    stops: path.steps.map((step) => placementOf(step.node)!),
  }));

  it("draws every run on one axis", () => {
    for (const { path, stops } of paths) {
      for (const [hop, points] of routeLines(stops).entries()) {
        for (let index = 0; index + 1 < points.length; index += 1) {
          const from = points[index]!;
          const to = points[index + 1]!;
          const straight = from.x === to.x || from.z === to.z;
          expect(straight, `${path.id} hop ${hop}`).toBe(true);
        }
      }
    }
  });

  it("never runs a route through a building it is not visiting", () => {
    for (const { path, stops } of paths) {
      for (const [hop, points] of routeLines(stops).entries()) {
        const endpoints = new Set([stops[hop]!.id, stops[hop + 1]!.id]);
        for (let index = 0; index + 1 < points.length; index += 1) {
          for (const placement of PLACEMENTS) {
            if (endpoints.has(placement.id)) continue;
            const clearance =
              distanceToRun(placement, points[index]!, points[index + 1]!) -
              radiusOf(placement.node);
            expect(clearance, `${path.id} hop ${hop} vs ${placement.id}`).toBeGreaterThan(0.4);
          }
        }
      }
    }
  });

  it("keeps two long hops off the same lane", () => {
    for (const { path, stops } of paths) {
      const lanes = routeLines(stops)
        .flat()
        .filter((point) => Math.abs(point.x) > 16)
        .map((point) => point.x);
      const runs = [...new Set(lanes)];
      for (const a of runs) {
        for (const b of runs) {
          if (a === b) continue;
          expect(Math.abs(a - b), path.id).toBeGreaterThan(0.5);
        }
      }
    }
  });
});

describe("architecture label placement", () => {
  const chip = (id: string, anchorX: number, anchorY: number): LabelCandidate => ({
    id,
    anchorX,
    anchorY,
    width: 120,
    height: 24,
  });

  it("never overlaps two chips, even when every anchor collides", () => {
    const candidates = Array.from({ length: 15 }, (_, index) =>
      chip(`node-${index}`, 400, 300 + (index % 3)),
    );
    const placed = placeLabels(candidates, { width: 900, height: 600 });

    expect(placed).toHaveLength(candidates.length);
    for (const a of placed) {
      for (const b of placed) {
        if (a === b) continue;
        const apart = Math.abs(a.y - b.y) >= 24 || Math.abs(a.x - b.x) >= 120;
        expect(apart, `${a.id} vs ${b.id}`).toBe(true);
      }
    }
  });

  it("keeps chips inside the canvas", () => {
    const placed = placeLabels([chip("edge", 890, 8), chip("corner", 4, 596)], {
      width: 900,
      height: 600,
    });
    for (const item of placed) {
      expect(item.x).toBeGreaterThanOrEqual(0);
      expect(item.y).toBeGreaterThanOrEqual(0);
      expect(item.x + 120).toBeLessThanOrEqual(900);
      expect(item.y + 24).toBeLessThanOrEqual(600);
    }
  });

  it("lets the highest priority chip keep the spot it asked for", () => {
    const [first] = placeLabels([chip("first", 400, 300), chip("second", 400, 300)], {
      width: 900,
      height: 600,
    });
    expect(first).toEqual({ id: "first", x: 340, y: 266 });
  });
});
