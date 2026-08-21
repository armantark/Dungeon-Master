import * as THREE from "three";

import type { ArchitecturePath } from "../../../lib/dev-architecture";
import {
  INK_RISE,
  groundAt,
  placementOf,
  routeLines,
  type RoutePoint,
} from "../../../lib/architecture-layout";
import { disposeObject } from "./city";

/**
 * Ink weights, lightest to heaviest. A hop is never coloured; it is only ever
 * drawn lighter or heavier, which is what keeps the sheet monochrome.
 */
const INK = {
  future: "#a3a28d",
  overview: "#6d6e5c",
  past: "#8b8c78",
  current: "#101109",
} as const;

type HopState = keyof typeof INK;

export interface RouteNetwork {
  group: THREE.Group;
  setCursor(cursor: number): void;
  /** Advances the travelling dot. Returns true while it wants more frames. */
  animate(elapsed: number): boolean;
  dispose(): void;
}

/** Offsets drawn either side of the hairline to thicken the current run. */
const WEIGHT = [-0.055, 0.055];

function polyline(points: readonly RoutePoint[], offset: number): THREE.BufferAttribute {
  const vertices: number[] = [];
  for (let index = 0; index + 1 < points.length; index += 1) {
    const from = points[index] as RoutePoint;
    const to = points[index + 1] as RoutePoint;
    // Every run is axis aligned, so the perpendicular is whichever axis is not
    // travelling. Corners open by the offset, and a joint dot covers each one.
    const shiftX = from.z === to.z ? 0 : offset;
    const shiftZ = from.z === to.z ? offset : 0;
    vertices.push(
      from.x + shiftX,
      groundAt(from.z) + INK_RISE,
      from.z + shiftZ,
      to.x + shiftX,
      groundAt(to.z) + INK_RISE,
      to.z + shiftZ,
    );
  }
  return new THREE.Float32BufferAttribute(vertices, 3);
}

/**
 * Draws the active path as sparse orthogonal ink on the ground plane.
 *
 * Every run is axis aligned and every corner carries a joint dot, so the eye
 * follows a route the way it follows a wiring diagram. Nothing arcs over the
 * buildings, so no run can be mistaken for structure.
 */
export function createRoutes(
  path: ArchitecturePath,
  allowMotion: boolean,
): RouteNetwork {
  const group = new THREE.Group();
  const materials = Object.fromEntries(
    Object.entries(INK).map(([state, color]) => [
      state,
      new THREE.LineBasicMaterial({ color }),
    ]),
  ) as Record<HopState, THREE.LineBasicMaterial>;

  const stops = path.steps.map((step) => {
    const placement = placementOf(step.node);
    if (!placement) throw new Error(`Route step ${step.node} has no plot`);
    return placement;
  });

  // Index alignment with `path.steps` is load-bearing: the trace cursor indexes
  // straight into these arrays.
  const lines = routeLines(stops);

  const hairlines = lines.map((points) => {
    const line = new THREE.LineSegments(
      new THREE.BufferGeometry().setAttribute("position", polyline(points, 0)),
      materials.overview,
    );
    line.raycast = () => {};
    group.add(line);
    return line;
  });

  // The current hop is thickened with lines drawn either side of it, because
  // WebGL ignores line width and a heavy run has to be real geometry.
  const heavy = lines.map((points) => {
    const run = new THREE.Group();
    for (const offset of WEIGHT) {
      const line = new THREE.LineSegments(
        new THREE.BufferGeometry().setAttribute("position", polyline(points, offset)),
        materials.current,
      );
      line.raycast = () => {};
      run.add(line);
    }
    run.visible = false;
    group.add(run);
    return run;
  });

  const jointGeometry = new THREE.CircleGeometry(0.11, 12);
  const joints = lines.map((points) => {
    const dots = new THREE.Group();
    for (const point of points) {
      const dot = new THREE.Mesh(
        jointGeometry,
        new THREE.MeshBasicMaterial({ color: INK.overview }),
      );
      dot.rotation.x = -Math.PI / 2;
      dot.position.set(point.x, groundAt(point.z) + INK_RISE + 0.004, point.z);
      dot.raycast = () => {};
      dots.add(dot);
    }
    group.add(dots);
    return dots;
  });

  const travel = new THREE.Mesh(
    new THREE.CircleGeometry(0.17, 16),
    new THREE.MeshBasicMaterial({ color: INK.current }),
  );
  travel.rotation.x = -Math.PI / 2;
  travel.raycast = () => {};
  travel.visible = false;
  group.add(travel);

  /** Corners of the current hop, walked leg by leg by the travelling dot. */
  let track: RoutePoint[] = [];
  let cursor = -1;
  let phase = 0;

  function paint(hop: number, state: HopState): void {
    (hairlines[hop] as THREE.LineSegments).material = materials[state];
    for (const dot of (joints[hop] as THREE.Group).children) {
      ((dot as THREE.Mesh).material as THREE.MeshBasicMaterial).color.set(INK[state]);
    }
  }

  const network: RouteNetwork = {
    group,

    setCursor(next: number): void {
      cursor = next;
      const hop = cursor - 1;

      for (let index = 0; index < hairlines.length; index += 1) {
        paint(
          index,
          cursor < 0 ? "overview" : index === hop ? "current" : index < hop ? "past" : "future",
        );
        (heavy[index] as THREE.Group).visible = index === hop;
      }

      track = hop >= 0 ? (lines[hop] ?? []) : [];
      travel.visible = allowMotion && track.length > 1;
      phase = 0;
    },

    animate(elapsed: number): boolean {
      if (!travel.visible || track.length < 2) return false;
      phase = (phase + elapsed * 0.22) % 1;
      const span = (track.length - 1) * phase;
      const leg = Math.min(track.length - 2, Math.floor(span));
      const from = track[leg] as RoutePoint;
      const to = track[leg + 1] as RoutePoint;
      const local = span - leg;
      const x = from.x + (to.x - from.x) * local;
      const z = from.z + (to.z - from.z) * local;
      travel.position.set(x, groundAt(z) + INK_RISE + 0.01, z);
      return true;
    },

    dispose(): void {
      disposeObject(group);
      jointGeometry.dispose();
      for (const material of Object.values(materials)) material.dispose();
      group.clear();
    },
  };

  network.setCursor(-1);
  return network;
}
