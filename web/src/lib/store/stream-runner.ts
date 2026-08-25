import type { StreamResult } from "../streaming";
import type {
  StreamError,
  StreamEvent,
  StreamFinalPayload,
  StreamFinalState,
  StreamStage,
  StreamStageStatus,
} from "../streaming-types";
import type { GameState } from "../types";

export interface StageProgress {
  stageId: string;
  label: string;
  status: StreamStageStatus;
  order: number;
  startedAt: number | null;
  completedAt: number | null;
}

export function applyStageEvent(
  stages: readonly StageProgress[],
  stage: StreamStage,
  now: number = performance.now(),
): StageProgress[] {
  const index = stages.findIndex((item) => item.stageId === stage.stage_id);
  if (index === -1) {
    return [
      ...stages,
      {
        stageId: stage.stage_id,
        label: stage.label,
        status: stage.status,
        order: stages.length,
        startedAt: stage.status === "active" ? now : null,
        completedAt:
          stage.status === "done" || stage.status === "skipped" ? now : null,
      },
    ];
  }

  const next = stages.slice();
  const existing = next[index]!;
  next[index] = {
    stageId: existing.stageId,
    label: stage.label,
    status: stage.status,
    order: existing.order,
    startedAt:
      stage.status === "active" && existing.startedAt === null
        ? now
        : existing.startedAt,
    completedAt:
      stage.status === "done" || stage.status === "skipped"
        ? now
        : existing.completedAt,
  };
  return next;
}

export type StateTerminal =
  | { kind: "state"; event: StreamFinalState }
  | { kind: "error"; event: StreamError }
  | { kind: "aborted"; reason: "client" | "server" };

/** Convert the transport result into the one terminal action the store owns. */
export function stateTerminal(result: StreamResult<StreamEvent>): StateTerminal {
  if (result.kind === "aborted") return result;
  if (result.kind === "error") return result;
  if (result.final.type !== "final_state") {
    return {
      kind: "error",
      event: {
        type: "error",
        message: `Expected final_state, received ${result.final.type}.`,
        code: "unexpected_terminal",
        state: null,
      },
    };
  }
  return { kind: "state", event: result.final };
}

export interface StateTerminalTarget {
  replaceState(state: GameState): void;
  reportError(message: string): void;
}

/** Apply one returned state-stream terminal exactly once. */
export function applyStateTerminal(
  terminal: StateTerminal,
  target: StateTerminalTarget,
): boolean {
  if (terminal.kind === "aborted") return false;
  if (terminal.kind === "state") {
    target.replaceState(terminal.event.state);
    return true;
  }
  target.reportError(terminal.event.message);
  if (terminal.event.state !== null) {
    target.replaceState(terminal.event.state);
  }
  return true;
}

export type PayloadTerminal =
  | { kind: "payload"; event: StreamFinalPayload }
  | { kind: "error"; event: StreamError }
  | { kind: "aborted"; reason: "client" | "server" };

export function payloadTerminal(result: StreamResult<StreamEvent>): PayloadTerminal {
  if (result.kind === "aborted") return result;
  if (result.kind === "error") return result;
  if (result.final.type !== "final_payload") {
    return {
      kind: "error",
      event: {
        type: "error",
        message: `Expected final_payload, received ${result.final.type}.`,
        code: "unexpected_terminal",
        state: null,
      },
    };
  }
  return { kind: "payload", event: result.final };
}
