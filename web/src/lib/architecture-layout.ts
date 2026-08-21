import {
  ARCHITECTURE_NODES,
  ARCHITECTURE_PATHS,
  type ArchitectureNode,
} from "./dev-architecture";

/**
 * Screen-aligned plan for the isometric drawing.
 *
 * The plan sits in a group yawed by `CITY_YAW`, which makes layout `+x` run
 * exactly screen-right and layout `+z` exactly screen-down under the fixed
 * isometric camera. Sections therefore become horizontal bands and streets
 * become rows, so two buildings can only crowd each other if the slot or
 * street spacing below is too small — which `architecture-layout.test.ts`
 * checks rather than leaving to chance.
 *
 * Buildings counter-rotate by the same yaw so their own faces stay
 * world-aligned. That matters: a box aligned to the band direction projects
 * with two faces exactly edge-on and reads as a flat card rather than a solid.
 */
export const CITY_YAW = Math.PI / 4;

/** Downward screen travel per unit of layout depth under the isometric camera. */
export const DEPTH_TO_SCREEN = 1 / Math.sqrt(3);
/** Upward screen travel per unit of world height under the isometric camera. */
export const HEIGHT_TO_SCREEN = Math.sqrt(2 / 3);

/** Where a layout point lands vertically on screen, in world units, down positive. */
export function screenDepth(z: number, y: number): number {
  return z * DEPTH_TO_SCREEN - y * HEIGHT_TO_SCREEN;
}

/** Thickness of the plate a section is drawn on. */
export const PLATE = 0.16;
/** Height of the plot every building stands on. */
export const PLOT_RISE = 0.16;
/** Height the route ink floats above a plate, clear of it but not detached. */
export const INK_RISE = 0.035;

export type ZoneId =
  | "frontend"
  | "transport"
  | "backend"
  | "persistence"
  | "desktop";

/**
 * Hatch is how a section identifies itself without colour: each plate is ruled
 * at its own angle and pitch, and Desktop & Delivery is the one cross-hatch.
 */
export interface Hatch {
  angles: readonly number[];
  spacing: number;
}

export interface Zone {
  id: ZoneId;
  /** Section number, printed on the plate and repeated in the left index. */
  index: number;
  label: string;
  detail: string;
  /** Height of the plate's top surface. */
  elevation: number;
  /** Plate footprint as [minX, maxX, minZ, maxZ]. */
  bounds: readonly [number, number, number, number];
  hatch: Hatch;
  /** Depths of the building rows on the plate. */
  streets: readonly number[];
}

/** Depth between two consecutive building rows. */
const STREET_GAP = 7;

/**
 * Sections read top to bottom in the order a turn travels, and step down in
 * elevation as they go, so the terracing repeats the reading order.
 */
export const ZONES: readonly Zone[] = [
  {
    id: "frontend",
    index: 1,
    label: "Frontend",
    detail: "Svelte + TypeScript",
    elevation: 1,
    bounds: [-16, 16, -3, 3],
    hatch: { angles: [0], spacing: 1.1 },
    streets: [0],
  },
  {
    id: "transport",
    index: 2,
    label: "Transport",
    detail: "HTTP + NDJSON",
    elevation: 0.7,
    bounds: [-16, 16, 4.5, 9.5],
    hatch: { angles: [Math.PI / 2], spacing: 0.9 },
    streets: [7],
  },
  {
    id: "backend",
    index: 3,
    label: "Backend",
    detail: "FastAPI, Python, model calls",
    elevation: 0.45,
    bounds: [-16, 16, 11, 24],
    hatch: { angles: [Math.PI / 4], spacing: 1.35 },
    streets: [14, 21],
  },
  {
    id: "persistence",
    index: 4,
    label: "Persistence",
    detail: "Canonical saves on disk",
    elevation: 0.2,
    bounds: [-16, 4, 25, 31],
    hatch: { angles: [-Math.PI / 4], spacing: 1.1 },
    streets: [28],
  },
  {
    id: "desktop",
    index: 5,
    label: "Desktop & Delivery",
    detail: "Tauri shell, sidecar, release",
    elevation: 0,
    bounds: [-16, 4, 32, 38],
    hatch: { angles: [0, Math.PI / 2], spacing: 1.6 },
    streets: [35],
  },
];

const ELEVATION = Object.fromEntries(
  ZONES.map((zone) => [zone.id, zone.elevation]),
) as Record<ZoneId, number>;

export interface NodePlacement {
  id: string;
  node: ArchitectureNode;
  zone: ZoneId;
  /** Two-letter drawing code, printed beside the building instead of a name. */
  code: string;
  x: number;
  z: number;
}

/**
 * Slots run street by street and then left to right, which is also the order
 * the left index lists them in, so keyboard tabbing walks the drawing the way
 * a reader's eye does.
 *
 * Relay Post sits in Transport rather than Frontend because its whole job is
 * the wire: resolve the API base, open the streaming request, hand the body on.
 */
const SLOTS: ReadonlyArray<readonly [string, ZoneId, string, number, number]> = [
  ["composer", "frontend", "CP", -13, 0],
  ["homes", "frontend", "ST", 13, 0],
  ["relay", "transport", "RL", -13, 7],
  ["depot", "backend", "DP", -13, 14],
  ["foundry", "backend", "FD", -6.5, 14],
  ["memory", "backend", "MM", 0, 14],
  ["router", "backend", "RT", 6.5, 14],
  ["oracle", "backend", "OR", 13, 14],
  ["loom", "backend", "LM", 0, 21],
  ["narrative", "backend", "NR", 6.5, 21],
  ["vault", "persistence", "VT", -6.5, 28],
  ["library", "persistence", "LB", 0, 28],
  ["crane", "desktop", "CR", -13, 35],
  ["sidecar", "desktop", "SC", -6.5, 35],
  ["shell", "desktop", "SH", 0, 35],
];

export const PLACEMENTS: readonly NodePlacement[] = SLOTS.map(
  ([id, zone, code, x, z]) => {
    const node = ARCHITECTURE_NODES.find((candidate) => candidate.id === id);
    if (!node) throw new Error(`Architecture layout references unknown node ${id}`);
    return { id, node, zone, code, x, z };
  },
);

const PLACEMENT_INDEX = new Map(PLACEMENTS.map((placement) => [placement.id, placement]));

export function placementOf(id: string): NodePlacement | undefined {
  return PLACEMENT_INDEX.get(id);
}

export function zoneOf(nodeId: string): ZoneId | undefined {
  return PLACEMENT_INDEX.get(nodeId)?.zone;
}

/** Placements of one section, in drawing order. */
export function membersOf(zone: ZoneId): readonly NodePlacement[] {
  return PLACEMENTS.filter((placement) => placement.zone === zone);
}

export function footprintOf(node: ArchitectureNode): { width: number; depth: number } {
  return { width: 0.8 + node.width * 0.52, depth: 0.8 + node.depth * 0.52 };
}

export function heightOf(node: ArchitectureNode): number {
  return 1 + node.height * 0.028;
}

/** Layout-space radius a counter-rotated building sweeps out on its street. */
export function radiusOf(node: ArchitectureNode): number {
  const { width, depth } = footprintOf(node);
  return Math.hypot(width, depth) / 2;
}

/** Plate surface a building stands on, before its own plot. */
export function groundOf(zone: ZoneId): number {
  return ELEVATION[zone];
}

/**
 * Surface height at a given depth. Between two plates there is no plate, so
 * the height ramps across the gap and a route drawn on the ground steps down
 * the terraces instead of hanging in the air.
 */
export function groundAt(z: number): number {
  const above = ZONES.filter((zone) => zone.bounds[3] < z).at(-1);
  const below = ZONES.find((zone) => zone.bounds[2] > z);
  const on = ZONES.find((zone) => z >= zone.bounds[2] && z <= zone.bounds[3]);
  if (on) return on.elevation;
  if (!above) return below?.elevation ?? 0;
  if (!below) return above.elevation;
  const span = below.bounds[2] - above.bounds[3];
  const travelled = (z - above.bounds[3]) / span;
  return above.elevation + (below.elevation - above.elevation) * travelled;
}

/* --- orthogonal ground routing ----------------------------------------- */

export interface RoutePoint {
  x: number;
  z: number;
}

/** Lanes outside every plate, where a hop that skips sections travels. */
const LANE = 16.8;
/** How far each successive lane hop steps further out, so two never coincide. */
const LANE_STEP = 0.75;

function dedupe(points: readonly RoutePoint[]): RoutePoint[] {
  return points.filter((point, index) => {
    const previous = points[index - 1];
    return !previous || previous.x !== point.x || previous.z !== point.z;
  });
}

/**
 * Turns the stops of one path into orthogonal ground polylines.
 *
 * Neighbouring streets are joined through the empty gutter between them. A hop
 * that skips sections leaves the grid instead and runs down an outer lane,
 * which is what stops a five-street jump from being drawn straight through
 * three sections of buildings. Successive lane hops step further out so two
 * long runs never land on the same ink.
 */
export function routeLines(stops: readonly NodePlacement[]): RoutePoint[][] {
  const laneUse = { left: 0, right: 0 };

  return stops.slice(1).map((to, index) => {
    const from = stops[index] as NodePlacement;
    if (from.z === to.z) {
      return dedupe([
        { x: from.x, z: from.z },
        { x: to.x, z: to.z },
      ]);
    }

    if (Math.abs(to.z - from.z) <= STREET_GAP + 0.001) {
      const gutter = (from.z + to.z) / 2;
      return dedupe([
        { x: from.x, z: from.z },
        { x: from.x, z: gutter },
        { x: to.x, z: gutter },
        { x: to.x, z: to.z },
      ]);
    }

    const side = from.x + to.x >= 0 ? "right" : "left";
    const lane = (side === "right" ? 1 : -1) * (LANE + laneUse[side] * LANE_STEP);
    laneUse[side] += 1;

    const travel = Math.sign(to.z - from.z);
    return dedupe([
      { x: from.x, z: from.z },
      { x: from.x, z: from.z + (travel * STREET_GAP) / 2 },
      { x: lane, z: from.z + (travel * STREET_GAP) / 2 },
      { x: lane, z: to.z - (travel * STREET_GAP) / 2 },
      { x: to.x, z: to.z - (travel * STREET_GAP) / 2 },
      { x: to.x, z: to.z },
    ]);
  });
}

/**
 * Widest reach of any route, plates included. The camera frames this rather
 * than the plates alone, because an outer lane runs past the plate edge and a
 * clipped run would read as a route that stops in mid-air.
 */
export const DRAWING_EXTENT = Math.max(
  ...ZONES.flatMap((zone) => [Math.abs(zone.bounds[0]), Math.abs(zone.bounds[1])]),
  ...ARCHITECTURE_PATHS.flatMap((path) =>
    routeLines(path.steps.map((step) => PLACEMENT_INDEX.get(step.node)!))
      .flat()
      .map((point) => Math.abs(point.x)),
  ),
);
