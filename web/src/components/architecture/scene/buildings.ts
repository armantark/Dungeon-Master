import * as THREE from "three";

import type { ArchitectureNode } from "../../../lib/dev-architecture";
import { CITY_YAW, PLOT_RISE, footprintOf, heightOf } from "../../../lib/architecture-layout";

/**
 * Drafting palette. Every solid is one of three pale paper tones, and the
 * only thing that separates its faces is the fixed light — which is what makes
 * the drawing read as ink on paper rather than as a lit render.
 */
const WALL = "#d9d4b9";
const ROOF = "#e8e4cd";
const TRIM = "#c5c0a4";

/** Ink weights. Emphasis is drawn, never coloured. */
const EDGE_PLAIN = "#4c4d40";
const EDGE_PATH = "#26271e";
const EDGE_FOCUS = "#101109";
/** Face wash a focused building is inked down toward. */
const WASH = new THREE.Color("#9c9880");

/** Fine ruled lines that keep a big blank face from reading as flat plastic. */
function createRuling(): THREE.Texture {
  const canvas = document.createElement("canvas");
  canvas.width = 8;
  canvas.height = 8;
  const context = canvas.getContext("2d");
  if (context) {
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, 8, 8);
    context.fillStyle = "#d7d4c4";
    context.fillRect(0, 7, 8, 1);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.magFilter = THREE.LinearFilter;
  return texture;
}

const RULING = createRuling();

export interface BuildingHandle {
  id: string;
  group: THREE.Group;
  /** Face materials, washed down when the building is inked in. */
  faces: THREE.MeshLambertMaterial[];
  /** One shared edge material per building carries the ink weight. */
  edges: THREE.LineBasicMaterial;
  /** Rooftop height in world units; the anchor for the drawing code. */
  anchorY: number;
  /** Plot centre, used to park the selection bracket. */
  ground: THREE.Vector3;
}

class Builder {
  readonly group = new THREE.Group();
  readonly faces: THREE.MeshLambertMaterial[] = [];
  readonly edges = new THREE.LineBasicMaterial({ color: EDGE_PLAIN });

  constructor(
    readonly node: ArchitectureNode,
    readonly width: number,
    readonly depth: number,
    readonly height: number,
  ) {}

  /**
   * Faces are pushed back by a polygon offset so their own outline always wins
   * the depth test. That is the whole z-fighting story here: no transparency,
   * no render-order tricks, no doubled geometry.
   */
  private material(tone: string, ruling: number): THREE.MeshLambertMaterial {
    const map = RULING.clone();
    map.needsUpdate = true;
    map.repeat.set(1, Math.max(1, Math.round(ruling)));
    const material = new THREE.MeshLambertMaterial({
      color: tone,
      map,
      flatShading: true,
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
    });
    material.userData.tone = new THREE.Color(tone);
    this.faces.push(material);
    return material;
  }

  add(
    geometry: THREE.BufferGeometry,
    tone: string,
    position: readonly [number, number, number],
  ): THREE.Mesh {
    geometry.computeBoundingBox();
    const size = geometry.boundingBox?.getSize(new THREE.Vector3()) ?? new THREE.Vector3(1, 1, 1);
    const mesh = new THREE.Mesh(geometry, this.material(tone, size.y * 3));
    mesh.position.set(...position);
    mesh.userData.nodeId = this.node.id;
    this.group.add(mesh);

    const outline = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 30), this.edges);
    // Lines are picked against a world-space threshold, so an outline can steal
    // a click from the solid in front of it. Only the faces are pickable.
    outline.raycast = () => {};
    mesh.add(outline);
    return mesh;
  }

  box(
    size: readonly [number, number, number],
    position: readonly [number, number, number],
    tone = WALL,
  ): THREE.Mesh {
    return this.add(new THREE.BoxGeometry(...size), tone, position);
  }

  cylinder(
    radius: number,
    height: number,
    position: readonly [number, number, number],
    tone = WALL,
    segments = 16,
  ): THREE.Mesh {
    return this.add(new THREE.CylinderGeometry(radius, radius, height, segments), tone, position);
  }

  cone(
    radius: number,
    height: number,
    position: readonly [number, number, number],
    segments = 4,
    tone = ROOF,
  ): THREE.Mesh {
    const mesh = this.add(new THREE.ConeGeometry(radius, height, segments), tone, position);
    if (segments === 4) mesh.rotation.y = Math.PI / 4;
    return mesh;
  }
}

/** Silhouettes. Every node kind gets a shape a reader can name from across the room. */
function shape(build: Builder): void {
  const { width: w, depth: d, height: h } = build;

  switch (build.node.kind) {
    case "gatehouse": {
      // Composer: the way in, so it is literally a gate you can walk through.
      for (const side of [-1, 1]) {
        build.box([w * 0.3, h, d], [side * w * 0.35, h / 2, 0]);
        build.box([w * 0.36, h * 0.1, d * 1.08], [side * w * 0.35, h * 1.02, 0], TRIM);
      }
      build.box([w * 0.46, h * 0.28, d * 0.72], [0, h * 0.84, 0], ROOF);
      break;
    }
    case "relay": {
      build.box([w, h * 0.66, d], [0, h * 0.33, 0]);
      build.box([w * 1.1, h * 0.09, d * 1.1], [0, h * 0.71, 0], TRIM);
      build.cylinder(0.055, h * 0.95, [0, h * 1.23, 0], TRIM, 8);
      build.cone(w * 0.28, h * 0.28, [0, h * 1.72, 0], 12, TRIM);
      break;
    }
    case "depot": {
      // Stream Depot: a long shed with an open bay, because frames leave here.
      build.box([w, h * 0.7, d], [0, h * 0.35, 0]);
      build.box([w * 1.05, h * 0.32, d * 1.05], [0, h * 0.86, 0], ROOF);
      build.box([w * 0.28, h * 0.42, d * 0.34], [w * 0.3, h * 0.21, d * 0.62], TRIM);
      break;
    }
    case "foundry": {
      build.box([w, h * 0.62, d], [0, h * 0.31, 0]);
      build.box([w * 1.04, h * 0.09, d * 1.04], [0, h * 0.66, 0], TRIM);
      build.box([w * 0.4, h * 0.34, d * 0.56], [-w * 0.62, h * 0.17, 0], TRIM);
      build.cylinder(w * 0.11, h * 0.86, [-w * 0.2, h * 1.03, -d * 0.2], WALL, 10);
      build.cylinder(w * 0.09, h * 1.12, [w * 0.16, h * 1.16, -d * 0.18], WALL, 10);
      break;
    }
    case "cistern": {
      build.cylinder(w * 0.44, h * 0.74, [0, h * 0.37, 0], WALL, 24);
      build.cylinder(w * 0.47, h * 0.07, [0, h * 0.5, 0], TRIM, 24);
      build.cylinder(w * 0.4, h * 0.12, [0, h * 0.8, 0], ROOF, 24);
      break;
    }
    case "observatory": {
      build.cylinder(w * 0.4, h * 0.7, [0, h * 0.35, 0], WALL, 20);
      const dome = build.add(
        new THREE.SphereGeometry(w * 0.42, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2),
        ROOF,
        [0, h * 0.7, 0],
      );
      dome.scale.y = 0.68;
      build.box([w * 0.1, h * 0.26, w * 0.44], [0, h * 0.8, w * 0.2], TRIM);
      break;
    }
    case "tower": {
      // Oracle: the tallest thing on the drawing, because Python decides outcomes.
      build.cylinder(w * 0.32, h, [0, h / 2, 0], WALL, 8);
      build.cylinder(w * 0.4, h * 0.09, [0, h * 0.98, 0], TRIM, 8);
      build.cone(w * 0.42, h * 0.32, [0, h * 1.19, 0], 8, ROOF);
      build.box([w * 0.64, h * 0.28, d * 0.64], [w * 0.5, h * 0.14, d * 0.26]);
      break;
    }
    case "theater": {
      build.box([w, h * 0.58, d * 0.88], [0, h * 0.29, -d * 0.06]);
      for (const offset of [-0.34, -0.11, 0.11, 0.34]) {
        build.cylinder(w * 0.045, h * 0.58, [offset * w, h * 0.29, d * 0.44], TRIM, 8);
      }
      build.box([w * 1.1, h * 0.09, d], [0, h * 0.62, 0], TRIM);
      build.cone(w * 0.7, h * 0.3, [0, h * 0.82, 0], 4, ROOF);
      break;
    }
    case "loom": {
      // Sawtooth north-light roof: a workshop that runs after the prose lands.
      build.box([w, h * 0.54, d], [0, h * 0.27, 0]);
      for (const offset of [-0.3, 0, 0.3]) {
        const tooth = build.box([w * 0.28, h * 0.28, d * 0.98], [offset * w, h * 0.66, 0], ROOF);
        tooth.rotation.z = -0.42;
      }
      break;
    }
    case "vault": {
      build.box([w, h * 0.7, d], [0, h * 0.35, 0]);
      for (const side of [-1, 1]) {
        build.box([w * 0.14, h * 0.56, d * 0.18], [side * w * 0.5, h * 0.28, d * 0.4], TRIM);
      }
      build.box([w * 1.08, h * 0.11, d * 1.08], [0, h * 0.75, 0], TRIM);
      build.add(new THREE.TorusGeometry(w * 0.2, w * 0.05, 8, 20), TRIM, [0, h * 0.3, d * 0.52]);
      break;
    }
    case "library": {
      build.box([w, h * 0.56, d], [0, h * 0.28, 0]);
      build.box([w * 1.06, h * 0.07, d * 1.06], [0, h * 0.59, 0], TRIM);
      build.box([w * 0.58, h * 0.26, d * 0.58], [0, h * 0.7, 0], ROOF);
      build.cone(w * 0.48, h * 0.26, [0, h * 0.96, 0], 4, ROOF);
      break;
    }
    case "homes": {
      // Client State District: a handful of houses, not one monolith.
      for (const [ox, oz, scale] of [
        [-0.32, 0.2, 0.95],
        [0.3, 0.26, 0.8],
        [0.02, -0.32, 0.68],
      ] as const) {
        build.box(
          [w * 0.4 * scale, h * 0.7 * scale, d * 0.42 * scale],
          [ox * w, h * 0.35 * scale, oz * d],
        );
        build.cone(w * 0.3 * scale, h * 0.36 * scale, [ox * w, h * 0.88 * scale, oz * d], 4, ROOF);
      }
      break;
    }
    case "shell": {
      build.box([w, h * 0.64, d], [0, h * 0.32, 0]);
      for (const sx of [-1, 1]) {
        for (const sz of [-1, 1]) {
          build.box([w * 0.13, h * 0.32, d * 0.13], [sx * w * 0.42, h * 0.8, sz * d * 0.42], TRIM);
        }
      }
      build.box([w * 1.04, h * 0.07, d * 1.04], [0, h * 0.67, 0], ROOF);
      break;
    }
    case "works": {
      build.box([w, h * 0.56, d], [0, h * 0.28, 0]);
      build.box([w * 0.42, h * 0.32, d * 0.42], [-w * 0.24, h * 0.72, 0], ROOF);
      const conveyor = build.box([w * 0.84, h * 0.07, d * 0.28], [w * 0.5, h * 0.58, 0], TRIM);
      conveyor.rotation.z = -0.4;
      break;
    }
    case "crane": {
      // Release Crane: a lattice mast and jib, unmistakably build machinery.
      build.box([w * 0.26, h, w * 0.26], [0, h / 2, 0]);
      for (const level of [0.28, 0.56, 0.84]) {
        build.box([w * 0.32, h * 0.035, w * 0.32], [0, h * level, 0], TRIM);
      }
      const jib = build.box([w * 1.7, h * 0.055, w * 0.14], [w * 0.5, h * 1.04, 0], TRIM);
      jib.rotation.z = -0.1;
      build.box([w * 0.34, h * 0.16, w * 0.28], [-w * 0.46, h * 0.99, 0]);
      build.cylinder(w * 0.028, h * 0.28, [w * 1.06, h * 0.88, 0], TRIM, 6);
      break;
    }
    default: {
      build.box([w, h * 0.66, d], [0, h * 0.33, 0]);
      build.cone(w * 0.6, h * 0.28, [0, h * 0.82, 0], 4, ROOF);
    }
  }
}

export function createBuilding(
  node: ArchitectureNode,
  position: { x: number; z: number; ground: number },
): BuildingHandle {
  const { width, depth } = footprintOf(node);
  const height = heightOf(node);
  const build = new Builder(node, width, depth, height);

  // A plot grounds each building against its plate and keeps its base faces
  // off the paving, so nothing is left coplanar to fight.
  build.box([width * 1.22, PLOT_RISE, depth * 1.22], [0, -PLOT_RISE / 2, 0], TRIM);

  shape(build);

  build.group.position.set(position.x, position.ground + PLOT_RISE, position.z);
  // Counter-rotate out of the band direction so the camera sees three faces of
  // every solid instead of one wall and a lid.
  build.group.rotation.y = -CITY_YAW;
  build.group.userData.nodeId = node.id;

  const box = new THREE.Box3().setFromObject(build.group);
  return {
    id: node.id,
    group: build.group,
    faces: build.faces,
    edges: build.edges,
    anchorY: box.max.y,
    ground: new THREE.Vector3(position.x, position.ground + PLOT_RISE + 0.02, position.z),
  };
}

export type BuildingMood = "plain" | "path" | "focus";

export function applyMood(handle: BuildingHandle, mood: BuildingMood): void {
  for (const material of handle.faces) {
    const tone = material.userData.tone as THREE.Color;
    material.color.copy(tone);
    if (mood === "focus") material.color.lerp(WASH, 0.42);
  }
  handle.edges.color.set(
    mood === "focus" ? EDGE_FOCUS : mood === "path" ? EDGE_PATH : EDGE_PLAIN,
  );
}
