import * as THREE from "three";

import {
  CITY_YAW,
  DRAWING_EXTENT,
  PLATE,
  PLACEMENTS,
  ZONES,
  groundOf,
  radiusOf,
  type Zone,
} from "../../../lib/architecture-layout";
import { createBuilding, type BuildingHandle } from "./buildings";

const UP = new THREE.Vector3(0, 1, 0);

/** Paper the whole drawing is printed on. */
export const PAPER = "#c7c4ab";
/** Plate faces, a shade off the paper so a section reads as a raised sheet. */
const PLATE_TOP = "#cfccb2";
const PLATE_EDGE = "#b6b399";
/** Hairline ink for hatching, and the heavier ink for a plate outline. */
const HATCH_INK = "#9a9880";
const PLATE_INK = "#5c5d4e";

export interface City {
  root: THREE.Group;
  buildings: Map<string, BuildingHandle>;
  pickables: THREE.Object3D[];
  selection: THREE.LineSegments;
  /** World points the camera must keep on screen. */
  frame: THREE.Vector3[];
}

/** Turns a layout-space point into the world point the camera sees. */
export function worldPoint(x: number, y: number, z: number): THREE.Vector3 {
  return new THREE.Vector3(x, y, z).applyAxisAngle(UP, CITY_YAW);
}

/**
 * A section is a thin ruled plate, not a lit block of ground.
 *
 * The plate carries three cues that survive a greyscale print: its own
 * elevation, its own hatch angle and pitch, and an inked outline. Nothing here
 * depends on colour, which is what lets a reader name a boundary at a glance.
 */
function plate(parent: THREE.Object3D, zone: Zone): void {
  const [minX, maxX, minZ, maxZ] = zone.bounds;
  const width = maxX - minX;
  const depth = maxZ - minZ;
  const centerX = (minX + maxX) / 2;
  const centerZ = (minZ + maxZ) / 2;
  const top = zone.elevation;

  const slab = new THREE.Mesh(
    new THREE.BoxGeometry(width, PLATE, depth),
    [
      new THREE.MeshBasicMaterial({ color: PLATE_EDGE }),
      new THREE.MeshBasicMaterial({ color: PLATE_EDGE }),
      new THREE.MeshBasicMaterial({ color: PLATE_TOP }),
      new THREE.MeshBasicMaterial({ color: PLATE_EDGE }),
      new THREE.MeshBasicMaterial({ color: PLATE_EDGE }),
      new THREE.MeshBasicMaterial({ color: PLATE_EDGE }),
    ].map((material) => {
      material.polygonOffset = true;
      material.polygonOffsetFactor = 2;
      material.polygonOffsetUnits = 2;
      return material;
    }),
  );
  slab.position.set(centerX, top - PLATE / 2, centerZ);
  parent.add(slab);

  const outline = new THREE.LineSegments(
    new THREE.EdgesGeometry(slab.geometry),
    new THREE.LineBasicMaterial({ color: PLATE_INK }),
  );
  outline.raycast = () => undefined;
  slab.add(outline);

  const points: number[] = [];
  for (const angle of zone.hatch.angles) {
    const along = new THREE.Vector2(Math.cos(angle), Math.sin(angle));
    const across = new THREE.Vector2(-along.y, along.x);
    // Rule the plate corner to corner along `across`, then clip each line to
    // the rectangle so the hatch stops exactly at the plate edge.
    const reach = (Math.abs(width * across.x) + Math.abs(depth * across.y)) / 2;
    for (let offset = -reach; offset <= reach; offset += zone.hatch.spacing) {
      const clipped = clipToRect(
        new THREE.Vector2(centerX + across.x * offset, centerZ + across.y * offset),
        along,
        minX + 0.12,
        maxX - 0.12,
        minZ + 0.12,
        maxZ - 0.12,
      );
      if (!clipped) continue;
      points.push(clipped[0].x, top + 0.008, clipped[0].y, clipped[1].x, top + 0.008, clipped[1].y);
    }
  }

  const hatch = new THREE.LineSegments(
    new THREE.BufferGeometry().setAttribute(
      "position",
      new THREE.Float32BufferAttribute(points, 3),
    ),
    new THREE.LineBasicMaterial({ color: HATCH_INK }),
  );
  hatch.raycast = () => undefined;
  parent.add(hatch);
}

/** Liang–Barsky clip of an infinite line to an axis-aligned rectangle. */
function clipToRect(
  point: THREE.Vector2,
  direction: THREE.Vector2,
  minX: number,
  maxX: number,
  minZ: number,
  maxZ: number,
): [THREE.Vector2, THREE.Vector2] | null {
  let enter = -Infinity;
  let exit = Infinity;
  for (const [delta, low, high, start] of [
    [direction.x, minX, maxX, point.x],
    [direction.y, minZ, maxZ, point.y],
  ] as const) {
    if (Math.abs(delta) < 1e-6) {
      if (start < low || start > high) return null;
      continue;
    }
    const first = (low - start) / delta;
    const second = (high - start) / delta;
    enter = Math.max(enter, Math.min(first, second));
    exit = Math.min(exit, Math.max(first, second));
  }
  if (exit - enter < 0.4) return null;
  return [
    point.clone().addScaledVector(direction, enter),
    point.clone().addScaledVector(direction, exit),
  ];
}

export function createCity(): City {
  const root = new THREE.Group();
  root.rotation.y = CITY_YAW;

  for (const zone of ZONES) plate(root, zone);

  const buildings = new Map<string, BuildingHandle>();
  const pickables: THREE.Object3D[] = [];
  for (const placement of PLACEMENTS) {
    const handle = createBuilding(placement.node, {
      x: placement.x,
      z: placement.z,
      ground: groundOf(placement.zone),
    });
    buildings.set(placement.id, handle);
    pickables.push(handle.group);
    root.add(handle.group);
  }

  // Four corner ticks rather than a ring: a drafting bracket that never hides
  // the plot it marks and never fights the ground hatch for the same pixels.
  const tick: number[] = [];
  for (const [sx, sz] of [
    [-1, -1],
    [1, -1],
    [-1, 1],
    [1, 1],
  ] as const) {
    tick.push(sx, 0, sz, sx * 0.55, 0, sz, sx, 0, sz, sx, 0, sz * 0.55);
  }
  const selection = new THREE.LineSegments(
    new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(tick, 3)),
    new THREE.LineBasicMaterial({ color: "#101109" }),
  );
  selection.raycast = () => undefined;
  selection.visible = false;
  root.add(selection);

  root.updateMatrixWorld(true);

  // Sample the shapes the camera has to hold rather than their bounding box:
  // the plan is yawed, so its world-space box is roughly twice its own area.
  const frame: THREE.Vector3[] = [];
  for (const zone of ZONES) {
    const [minX, maxX, minZ, maxZ] = zone.bounds;
    for (const x of [minX, maxX]) {
      for (const z of [minZ, maxZ]) frame.push(worldPoint(x, zone.elevation, z));
    }
  }
  for (const placement of PLACEMENTS) {
    const handle = buildings.get(placement.id);
    if (!handle) continue;
    const reach = radiusOf(placement.node);
    frame.push(worldPoint(placement.x, handle.anchorY, placement.z - reach));
  }
  for (const side of [-DRAWING_EXTENT, DRAWING_EXTENT]) frame.push(worldPoint(side, 0, 0));

  return { root, buildings, pickables, selection, frame };
}

export function disposeObject(object: THREE.Object3D): void {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  object.traverse((child) => {
    const drawable = child as Partial<THREE.Mesh>;
    if (drawable.geometry) geometries.add(drawable.geometry);
    const material = drawable.material;
    if (material) {
      for (const entry of Array.isArray(material) ? material : [material]) materials.add(entry);
    }
  });
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) material.dispose();
}
