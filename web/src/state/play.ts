import type { AcquireVerb } from "../lib/slash";
import type { OracleOutcome } from "../lib/types";

export interface ClientNote {
  id: string;
  kind: "help" | "error" | "info" | "explanation" | "oracle_preview";
  text: string;
  created_at: string;
  question?: string;
}

function noteId(): string {
  return `note_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function createClientNote(kind: ClientNote["kind"], text: string): ClientNote {
  return { id: noteId(), kind, text, created_at: new Date().toISOString() };
}

export function createExplanationNote(question: string, answer: string): ClientNote {
  return {
    ...createClientNote("explanation", answer),
    question,
  };
}

export function createOraclePreviewNote(
  question: string,
  outcome: OracleOutcome,
): ClientNote {
  const answer = outcome.answer ?? outcome.summary;
  const roll = outcome.rolls[0];
  const lines = [
    "**Oracle preview**",
    "",
    `**Answer:** ${answer}`,
    `**Likelihood:** ${outcome.likelihood ?? "Even odds"}`,
  ];
  if (outcome.probability !== null) {
    lines.push(`**Adjusted chance:** ${outcome.probability}%`);
  }
  if (roll !== undefined) {
    lines.push(`**Roll:** ${roll.result} / ${roll.sides}`);
  }
  lines.push("", "_This does not commit the turn or advance the scene._");
  return {
    ...createClientNote("oracle_preview", lines.join("\n")),
    question,
  };
}

export function buildRetreatPrompt(reason: string): string {
  const cleaned = reason.trim();
  if (!cleaned) return "I attempt to retreat from combat.";
  return `I attempt to retreat from combat: ${cleaned}`;
}

export function buildAcquirePrompt(verb: AcquireVerb, body: string): string {
  const cleaned = body.trim();
  if (!cleaned) return `I ${verb} the offered item.`;
  const ending = cleaned.slice(-1);
  const needsTerminator = ending !== "." && ending !== "!" && ending !== "?";
  return `I ${verb} ${cleaned}${needsTerminator ? "." : ""}`;
}
