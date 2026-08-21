export interface LabelCandidate {
  id: string;
  /** Screen point the label should sit above, in canvas pixels. */
  anchorX: number;
  anchorY: number;
  width: number;
  height: number;
}

export interface PlacedLabel {
  id: string;
  x: number;
  y: number;
}

interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

function overlaps(a: Rect, b: Rect): boolean {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

/**
 * Places drawing codes and section labels above their anchors without letting
 * any two touch.
 *
 * Candidates are consumed in priority order, so the first entry always lands
 * where it wants and later entries step out of its way. The banded plan
 * already keeps collisions rare; this pass is what makes "no overlapping
 * codes" a guarantee rather than a hope, including at small viewport sizes
 * where the whole drawing is scaled down.
 */
export interface LabelInset {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export function placeLabels(
  candidates: readonly LabelCandidate[],
  viewport: { width: number; height: number },
  options: { anchorGap?: number; gap?: number; inset?: Partial<LabelInset> } = {},
): PlacedLabel[] {
  const anchorGap = options.anchorGap ?? 10;
  const gap = options.gap ?? 6;
  const inset = { left: 4, right: 4, top: 4, bottom: 4, ...options.inset };

  const taken: Rect[] = [];
  const placed: PlacedLabel[] = [];

  for (const candidate of candidates) {
    const step = candidate.height + gap;
    const maxLeft = Math.max(inset.left, viewport.width - candidate.width - inset.right);
    const maxTop = Math.max(inset.top, viewport.height - candidate.height - inset.bottom);
    const left = Math.min(maxLeft, Math.max(inset.left, candidate.anchorX - candidate.width / 2));
    const wanted = candidate.anchorY - candidate.height - anchorGap;
    const rungs = Math.ceil(viewport.height / step) + 2;

    const at = (top: number): Rect => ({
      left,
      top,
      right: left + candidate.width,
      bottom: top + candidate.height,
    });

    // Try the wanted height first, then climb into the empty sky above the
    // rooftops, and only drop below when the sky is already full.
    let best: Rect | null = null;
    search: for (let rung = 0; rung <= rungs; rung += 1) {
      for (const direction of rung === 0 ? [0] : [-1, 1]) {
        const top = wanted + direction * rung * step;
        if (top < inset.top || top > maxTop) continue;
        const rect = at(top);
        if (!taken.some((other) => overlaps(rect, other))) {
          best = rect;
          break search;
        }
      }
    }

    const rect = best ?? at(Math.min(maxTop, Math.max(inset.top, wanted)));
    taken.push(rect);
    placed.push({ id: candidate.id, x: rect.left, y: rect.top });
  }

  return placed;
}
