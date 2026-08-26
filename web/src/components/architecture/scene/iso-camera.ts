import * as THREE from "three";

const UP = new THREE.Vector3(0, 1, 0);
/** Fixed true-isometric view direction. Nothing rotates the camera. */
const DIRECTION = new THREE.Vector3(1, 1, 1).normalize();
const STANDOFF = 160;
const MIN_VIEW = 7;
const MAX_VIEW = 120;

export interface Padding {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface IsoCamera {
  camera: THREE.OrthographicCamera;
  setViewport(width: number, height: number): void;
  /**
   * Fits the given world points inside the viewport minus `padding`.
   *
   * Points rather than a `Box3`: the city is yawed 45 degrees, so its
   * world-space bounding box is roughly twice the area of the city itself and
   * framing from it would shrink the map to half the size it can afford.
   */
  frame(points: readonly THREE.Vector3[], padding: Padding, immediate: boolean): void;
  zoomBy(factor: number): void;
  panBy(deltaX: number, deltaY: number): void;
  /** Advances the ease. Returns true while the view is still settling. */
  step(elapsed: number): boolean;
}

/**
 * Orthographic isometric camera with pan and zoom but no rotation.
 *
 * Locking the orbit is deliberate: the whole layout depends on the fixed view
 * direction, so letting a reader spin the city would break the district bands,
 * the label placement guarantees and the flat conduit network at once.
 */
export function createIsoCamera(): IsoCamera {
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 400);
  const forward = DIRECTION.clone().negate();
  const right = new THREE.Vector3().crossVectors(forward, UP).normalize();
  const up = new THREE.Vector3().crossVectors(right, forward).normalize();

  const target = new THREE.Vector3();
  const goalTarget = new THREE.Vector3();
  let viewHeight = 40;
  let goalViewHeight = 40;
  let width = 1;
  let height = 1;

  function apply(): void {
    const aspect = width / height;
    camera.top = viewHeight / 2;
    camera.bottom = -viewHeight / 2;
    camera.left = (-viewHeight * aspect) / 2;
    camera.right = (viewHeight * aspect) / 2;
    camera.position.copy(target).addScaledVector(DIRECTION, STANDOFF);
    camera.lookAt(target);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
  }

  function pixelsPerUnit(): number {
    return height / viewHeight;
  }

  const controller: IsoCamera = {
    camera,

    setViewport(nextWidth: number, nextHeight: number): void {
      width = Math.max(1, nextWidth);
      height = Math.max(1, nextHeight);
      apply();
    },

    frame(points: readonly THREE.Vector3[], padding: Padding, immediate: boolean): void {
      if (points.length === 0) return;
      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;
      for (const point of points) {
        const screenX = point.dot(right);
        const screenY = point.dot(up);
        minX = Math.min(minX, screenX);
        maxX = Math.max(maxX, screenX);
        minY = Math.min(minY, screenY);
        maxY = Math.max(maxY, screenY);
      }

      const availableWidth = Math.max(32, width - padding.left - padding.right);
      const availableHeight = Math.max(32, height - padding.top - padding.bottom);
      const scale = Math.min(
        availableWidth / Math.max(0.001, maxX - minX),
        availableHeight / Math.max(0.001, maxY - minY),
      );

      goalViewHeight = THREE.MathUtils.clamp(height / scale, MIN_VIEW, MAX_VIEW);
      const offsetX = padding.left + availableWidth / 2 - width / 2;
      const offsetY = padding.top + availableHeight / 2 - height / 2;
      const perUnit = height / goalViewHeight;
      goalTarget
        .set(0, 0, 0)
        .addScaledVector(right, (minX + maxX) / 2 - offsetX / perUnit)
        .addScaledVector(up, (minY + maxY) / 2 + offsetY / perUnit);

      if (immediate) {
        target.copy(goalTarget);
        viewHeight = goalViewHeight;
        apply();
      }
    },

    zoomBy(factor: number): void {
      goalViewHeight = THREE.MathUtils.clamp(goalViewHeight / factor, MIN_VIEW, MAX_VIEW);
    },

    panBy(deltaX: number, deltaY: number): void {
      const perUnit = pixelsPerUnit();
      goalTarget.addScaledVector(right, -deltaX / perUnit);
      goalTarget.addScaledVector(up, deltaY / perUnit);
      target.copy(goalTarget);
      apply();
    },

    step(elapsed: number): boolean {
      const settled =
        target.distanceToSquared(goalTarget) < 1e-6 && Math.abs(viewHeight - goalViewHeight) < 1e-3;
      if (settled) {
        target.copy(goalTarget);
        viewHeight = goalViewHeight;
        apply();
        return false;
      }
      const blend = 1 - Math.exp(-elapsed / 0.085);
      target.lerp(goalTarget, blend);
      viewHeight += (goalViewHeight - viewHeight) * blend;
      apply();
      return true;
    },
  };

  return controller;
}
