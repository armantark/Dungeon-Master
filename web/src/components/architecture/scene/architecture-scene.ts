import * as THREE from "three";

import type { ArchitecturePath } from "../../../lib/dev-architecture";
import {
  CITY_YAW,
  ZONES,
  footprintOf,
  placementOf,
  radiusOf,
  type ZoneId,
} from "../../../lib/architecture-layout";
import { applyMood } from "./buildings";
import { PAPER, createCity, disposeObject, worldPoint } from "./city";
import { createIsoCamera, type Padding } from "./iso-camera";
import { createRoutes, type RouteNetwork } from "./routes";

const UP = new THREE.Vector3(0, 1, 0);

export interface ScreenPoint {
  x: number;
  y: number;
}

export interface SceneAnchors {
  width: number;
  height: number;
  /** Rooftop of every building, where its drawing code is printed. */
  nodes: Map<string, ScreenPoint>;
  /** Top-left corner of every plate, where its section label is printed. */
  zones: Map<ZoneId, ScreenPoint>;
}

export interface SceneState {
  path: ArchitecturePath;
  traceIndex: number;
  selectedNodeId: string;
  hoveredNodeId: string | null;
  compact: boolean;
}

export interface SceneOptions {
  canvas: HTMLCanvasElement;
  reducedMotion: boolean;
  onHover: (id: string | null) => void;
  onPick: (id: string) => void;
  onAnchors: (anchors: SceneAnchors) => void;
}

export interface ArchitectureSceneApi {
  setState(state: SceneState): void;
  setViewport(width: number, height: number): void;
  zoomBy(factor: number): void;
  fit(): void;
  dispose(): void;
}

/**
 * Reserved margins, in canvas pixels. The left margin is the column the five
 * section labels print in; the rest is just breathing room for the codes.
 */
const WIDE_MARGIN: Padding = { left: 84, right: 34, top: 34, bottom: 26 };
const COMPACT_MARGIN: Padding = { left: 20, right: 16, top: 30, bottom: 20 };

export function createArchitectureScene(options: SceneOptions): ArchitectureSceneApi {
  const { canvas } = options;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(PAPER);

  const city = createCity();
  scene.add(city.root);

  // Flat drafting light: a wide ambient plus one fixed key, aimed so the three
  // faces the isometric camera can see land on three distinct paper values.
  scene.add(new THREE.AmbientLight("#ffffff", 0.62));
  const key = new THREE.DirectionalLight("#ffffff", 0.5);
  key.position.set(0.55, 0.78, 0.3);
  scene.add(key);

  const iso = createIsoCamera();

  let routes: RouteNetwork | null = null;
  let routePathId: ArchitecturePath["id"] | null = null;
  let state: SceneState | null = null;
  let width = 1;
  let height = 1;
  let frameId = 0;
  let lastFrameTime = 0;

  function margin(): Padding {
    return state?.compact ? COMPACT_MARGIN : WIDE_MARGIN;
  }

  /**
   * Points the camera must hold. Narrow viewports follow the active hop
   * instead of the whole plan, which is what makes a 390px screen usable.
   */
  function focusPoints(): readonly THREE.Vector3[] {
    if (!state?.compact || state.traceIndex < 1) return city.frame;
    const points: THREE.Vector3[] = [];
    for (const step of [
      state.path.steps[state.traceIndex - 1],
      state.path.steps[state.traceIndex],
    ]) {
      const placement = step ? placementOf(step.node) : undefined;
      const handle = step ? city.buildings.get(step.node) : undefined;
      if (!placement || !handle) continue;
      const reach = radiusOf(placement.node) + 2.4;
      for (const offsetX of [-reach, reach]) {
        for (const offsetZ of [-reach, reach]) {
          points.push(worldPoint(placement.x + offsetX, handle.ground.y, placement.z + offsetZ));
          points.push(worldPoint(placement.x + offsetX, handle.anchorY, placement.z + offsetZ));
        }
      }
    }
    return points.length > 0 ? points : city.frame;
  }

  function refit(immediate: boolean): void {
    iso.frame(focusPoints(), margin(), immediate);
    requestFrame();
  }

  const projected = new THREE.Vector3();
  function project(point: THREE.Vector3): ScreenPoint {
    projected.copy(point).project(iso.camera);
    return {
      x: (projected.x * 0.5 + 0.5) * width,
      y: (-projected.y * 0.5 + 0.5) * height,
    };
  }

  const anchorPoint = new THREE.Vector3();
  function publishAnchors(): void {
    const nodes = new Map<string, ScreenPoint>();
    for (const [id, handle] of city.buildings) {
      const placement = placementOf(id);
      if (!placement) continue;
      anchorPoint.set(placement.x, handle.anchorY, placement.z).applyAxisAngle(UP, CITY_YAW);
      nodes.set(id, project(anchorPoint));
    }

    const zones = new Map<ZoneId, ScreenPoint>();
    for (const zone of ZONES) {
      anchorPoint
        .set(zone.bounds[0] - 0.6, zone.elevation, zone.bounds[2])
        .applyAxisAngle(UP, CITY_YAW);
      zones.set(zone.id, project(anchorPoint));
    }

    options.onAnchors({ width, height, nodes, zones });
  }

  function requestFrame(): void {
    // Nothing is worth drawing, or measuring anchors against, until the resize
    // observer has reported a real viewport.
    if (frameId || width < 2 || height < 2) return;
    frameId = requestAnimationFrame(tick);
  }

  function tick(now: number): void {
    frameId = 0;
    const elapsed = lastFrameTime ? Math.min(0.05, (now - lastFrameTime) / 1000) : 0.016;
    lastFrameTime = now;

    const moving = iso.step(options.reducedMotion ? 10 : elapsed);
    const travelling = routes?.animate(elapsed) ?? false;

    renderer.render(scene, iso.camera);
    publishAnchors();
    if (moving || travelling) requestFrame();
    else lastFrameTime = 0;
  }

  function applyState(next: SceneState): void {
    const previous = state;
    state = next;

    if (routePathId !== next.path.id) {
      routes?.dispose();
      if (routes) city.root.remove(routes.group);
      routes = createRoutes(next.path, !options.reducedMotion);
      city.root.add(routes.group);
      routePathId = next.path.id;
    }
    routes?.setCursor(next.traceIndex);

    const onPath = new Set(next.path.steps.map((step) => step.node));
    for (const [id, handle] of city.buildings) {
      const focused = id === next.selectedNodeId || id === next.hoveredNodeId;
      applyMood(handle, focused ? "focus" : onPath.has(id) ? "path" : "plain");
    }

    const selected = city.buildings.get(next.selectedNodeId);
    const placement = placementOf(next.selectedNodeId);
    if (selected && placement) {
      const { width: plot, depth } = footprintOf(placement.node);
      city.selection.visible = true;
      city.selection.position.copy(selected.ground);
      // The bracket squares up with the building, which is counter-rotated out
      // of the plan's yaw so its own faces stay world aligned.
      city.selection.rotation.y = -CITY_YAW;
      city.selection.scale.set(plot * 0.72 + 0.2, 1, depth * 0.72 + 0.2);
    } else {
      city.selection.visible = false;
    }

    const reframe =
      previous?.path.id !== next.path.id ||
      previous?.compact !== next.compact ||
      (next.compact && previous?.traceIndex !== next.traceIndex);
    if (reframe) iso.frame(focusPoints(), margin(), options.reducedMotion || !previous);
    requestFrame();
  }

  /* --- pointer handling ------------------------------------------------- */

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let dragPointer: number | null = null;
  let dragged = 0;
  let lastX = 0;
  let lastY = 0;

  function nodeAt(event: PointerEvent): string | null {
    const rect = canvas.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, iso.camera);
    for (const hit of raycaster.intersectObjects(city.pickables, true)) {
      let object: THREE.Object3D | null = hit.object;
      while (object) {
        if (typeof object.userData.nodeId === "string") return object.userData.nodeId;
        object = object.parent;
      }
    }
    return null;
  }

  function handlePointerDown(event: PointerEvent): void {
    dragged = 0;
    lastX = event.clientX;
    lastY = event.clientY;
    if (event.pointerType === "touch") return;
    dragPointer = event.pointerId;
    canvas.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent): void {
    if (dragPointer === event.pointerId && event.buttons > 0) {
      const deltaX = event.clientX - lastX;
      const deltaY = event.clientY - lastY;
      lastX = event.clientX;
      lastY = event.clientY;
      dragged += Math.abs(deltaX) + Math.abs(deltaY);
      if (dragged > 4) {
        canvas.style.cursor = "grabbing";
        iso.panBy(deltaX, deltaY);
        requestFrame();
      }
      return;
    }
    const id = nodeAt(event);
    canvas.style.cursor = id ? "pointer" : "grab";
    options.onHover(id);
  }

  function handlePointerUp(event: PointerEvent): void {
    if (dragPointer === event.pointerId) {
      dragPointer = null;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      canvas.style.cursor = "grab";
    }
    if (dragged > 4) return;
    const id = nodeAt(event);
    if (id) options.onPick(id);
  }

  function handlePointerLeave(): void {
    options.onHover(null);
    canvas.style.cursor = "grab";
  }

  function handleWheel(event: WheelEvent): void {
    event.preventDefault();
    iso.zoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12);
    requestFrame();
  }

  canvas.addEventListener("pointerdown", handlePointerDown);
  canvas.addEventListener("pointermove", handlePointerMove);
  canvas.addEventListener("pointerup", handlePointerUp);
  canvas.addEventListener("pointerleave", handlePointerLeave);
  canvas.addEventListener("pointercancel", handlePointerLeave);
  canvas.addEventListener("wheel", handleWheel, { passive: false });

  return {
    setState: applyState,

    setViewport(nextWidth: number, nextHeight: number): void {
      width = Math.max(1, Math.round(nextWidth));
      height = Math.max(1, Math.round(nextHeight));
      renderer.setSize(width, height, false);
      iso.setViewport(width, height);
      refit(true);
    },

    zoomBy(factor: number): void {
      iso.zoomBy(factor);
      requestFrame();
    },

    fit(): void {
      refit(options.reducedMotion);
    },

    dispose(): void {
      if (frameId) cancelAnimationFrame(frameId);
      frameId = 0;
      canvas.removeEventListener("pointerdown", handlePointerDown);
      canvas.removeEventListener("pointermove", handlePointerMove);
      canvas.removeEventListener("pointerup", handlePointerUp);
      canvas.removeEventListener("pointerleave", handlePointerLeave);
      canvas.removeEventListener("pointercancel", handlePointerLeave);
      canvas.removeEventListener("wheel", handleWheel);
      routes?.dispose();
      routes = null;
      disposeObject(scene);
      scene.clear();
      // Dev-only route, but hot reloads mount this repeatedly and browsers cap
      // live WebGL contexts, so hand the context back explicitly.
      renderer.forceContextLoss();
      renderer.dispose();
    },
  };
}
