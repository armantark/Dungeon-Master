import type { OracleOutcome } from "../lib/types";
import type { StreamRoute } from "./stream/streaming-types";
import type { StageProgress } from "./stream-runner";

export type RollPhase = "idle" | "rolling" | "settling";

export interface StreamingState {
  active: boolean;
  route: StreamRoute | null;
  requestId: string | null;
  content: string;
  thinking: string;
  pendingOutcome: OracleOutcome | null;
  resuming: boolean;
  stages: StageProgress[];
}

export function emptyStreamingState(): StreamingState {
  return {
    active: false,
    route: null,
    requestId: null,
    content: "",
    thinking: "",
    pendingOutcome: null,
    resuming: false,
    stages: [],
  };
}
