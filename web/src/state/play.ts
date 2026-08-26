import { api } from "../lib/api";
import { parseTurn, SLASH_HELP } from "../lib/slash";
import type { AcquireVerb } from "../lib/slash";
import type {
  CampaignEndReason,
  CampaignSeed,
  CharacterQuiz,
  CharacterQuizAnswer,
  CharacterSheet,
  GameState,
  Likelihood,
  OracleOutcome,
} from "../lib/types";
import { saveOocNotes } from "./save/ooc-notes";
import { StreamWorkflow } from "./stream";

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

export function createOraclePreviewNote(question: string, outcome: OracleOutcome): ClientNote {
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

interface CampaignStateOwner {
  state: GameState | null;
  error: string | null;
  notes: ClientNote[];
  activeSaveId: string | null;
}

/** Owns setup generation, campaign lifecycle, oracle actions, and Composer dispatch. */
export class CampaignWorkflow {
  readonly #owner: CampaignStateOwner;
  readonly #requests: StreamWorkflow;

  constructor(owner: CampaignStateOwner, requests: StreamWorkflow) {
    this.#owner = owner;
    this.#requests = requests;
  }

  async reset(): Promise<void> {
    await this.#requests.runState((signal) => api.reset(signal), { cancelLabel: "Stop reset" });
  }

  async setChaos(value: number): Promise<void> {
    await this.#requests.runState((signal) => api.setChaos(value, signal));
  }

  async updateNotes(settingNotes: string, playerNotes: string): Promise<void> {
    await this.#requests.runState((signal) => api.updateNotes(settingNotes, playerNotes, signal));
  }

  async updateDirectives(worldGuidance: string, playGuidance: string): Promise<void> {
    await this.#requests.runState((signal) =>
      api.updateDirectives(worldGuidance, playGuidance, signal),
    );
  }

  async updateCampaignSeed(seed: CampaignSeed): Promise<void> {
    await this.#requests.runState((signal) => api.updateCampaignSeed(seed, signal));
  }

  async askYesNo(question: string, likelihood: Likelihood): Promise<void> {
    const cleaned = question.trim();
    if (!cleaned) return;
    const outcome = await this.#requests.call(
      (signal) => api.previewYesNo(cleaned, likelihood, signal),
      { cancelLabel: "Stop preview" },
    );
    if (outcome !== null) this.#oraclePreviewNote(cleaned, outcome);
  }

  async randomEvent(): Promise<void> {
    await this.#requests.runWithRoll((signal) => api.randomEvent(signal));
  }

  async sceneCheck(expectedScene: string): Promise<void> {
    await this.#requests.runWithRoll((signal) => api.sceneCheck(expectedScene, signal));
  }

  async submitAction(action: string): Promise<void> {
    await this.#requests.runStateStream({
      stream: (handlers, signal) => api.streamSubmitAction(action, handlers, signal),
      fallback: (signal) => api.submitAction(action, signal),
      cancelLabel: "Stop response",
      rollAware: false,
    });
  }

  async explain(question: string): Promise<void> {
    const cleaned = question.trim();
    if (!cleaned) return;
    const answer = await this.#requests.runPayloadStream<string>({
      stream: (handlers, signal) => api.streamExplain(cleaned, handlers, signal),
      fallback: async (signal) => (await api.explain(cleaned, signal)).answer,
      finalKind: "explanation",
      extract: (payload) => (payload as { answer: string }).answer,
      cancelLabel: "Stop explaining",
    });
    const trimmed = answer?.trim() ?? "";
    if (trimmed !== "") this.#explanationNote(cleaned, trimmed);
  }

  async submitTurn(text: string): Promise<void> {
    await this.#requests.runStateStream({
      stream: (handlers, signal) => api.streamSubmitTurn(text, handlers, signal),
      fallback: (signal) => api.submitTurn(text, signal),
      cancelLabel: "Stop response",
      rollAware: true,
    });
  }

  async fetchCharacterTemplates(): Promise<CharacterSheet[]> {
    const response = await this.#requests.call((signal) => api.getCharacterTemplates(signal), {
      cancelLabel: "Stop templates",
    });
    return response?.templates ?? [];
  }

  async generateCharacterDraft(
    mode: "scratch" | "template",
    prompt?: string,
    template?: CharacterSheet,
  ): Promise<CharacterSheet | null> {
    return await this.#requests.runPayloadStream<CharacterSheet>({
      stream: (handlers, signal) =>
        api.streamCharacterDraft(mode, handlers, prompt, template, signal),
      fallback: async (signal) =>
        (await api.generateCharacterDraft(mode, prompt, template, signal)).draft,
      finalKind: "character_draft",
      extract: (payload) => (payload as { draft: CharacterSheet }).draft,
      cancelLabel: "Stop draft",
    });
  }

  async generateCharacterQuiz(concept: string): Promise<CharacterQuiz | null> {
    return await this.#requests.runPayloadStream<CharacterQuiz>({
      stream: (handlers, signal) => api.streamCharacterQuiz(concept, handlers, signal),
      fallback: async (signal) => (await api.generateCharacterQuiz(concept, signal)).quiz,
      finalKind: "character_quiz",
      extract: (payload) => (payload as { quiz: CharacterQuiz }).quiz,
      cancelLabel: "Stop interview",
    });
  }

  async generateQuizzedCharacterDraft(
    concept: string,
    answers: CharacterQuizAnswer[],
    finalNote: string | null,
  ): Promise<CharacterSheet | null> {
    return await this.#requests.runPayloadStream<CharacterSheet>({
      stream: (handlers, signal) =>
        api.streamQuizzedCharacterDraft(concept, answers, finalNote, handlers, signal),
      fallback: async (signal) =>
        (await api.generateQuizzedCharacterDraft(concept, answers, finalNote, signal)).draft,
      finalKind: "character_draft",
      extract: (payload) => (payload as { draft: CharacterSheet }).draft,
      cancelLabel: "Stop draft",
    });
  }

  async finalizeCharacter(character: CharacterSheet): Promise<void> {
    await this.#requests.runState((signal) => api.finalizeCharacter(character, signal), {
      cancelLabel: "Stop finalize",
    });
  }

  async endCampaign(reason: CampaignEndReason, summary: string): Promise<void> {
    const trimmed = summary.trim();
    await this.#requests.runState(
      (signal) => api.endCampaign(reason, trimmed === "" ? null : trimmed, signal),
      { cancelLabel: "Stop close" },
    );
  }

  async startCampaign(): Promise<void> {
    await this.#requests.runStateStream({
      stream: (handlers, signal) => api.streamStartCampaign(handlers, signal),
      fallback: (signal) => api.startCampaign(signal),
      cancelLabel: "Stop generation",
      rollAware: false,
    });
  }

  async regenerateMessage(eventId: string): Promise<void> {
    await this.#requests.runStateStream({
      stream: (handlers, signal) => api.streamRegenerateMessage(eventId, handlers, signal),
      fallback: (signal) => api.regenerateMessage(eventId, signal),
      cancelLabel: "Stop repair",
      rollAware: true,
    });
  }

  async submit(rawText: string): Promise<boolean> {
    const parsed = parseTurn(rawText);
    switch (parsed.kind) {
      case "error":
        if (parsed.message) this.#note("error", parsed.message);
        return parsed.message !== "";
      case "help":
        this.#note("help", SLASH_HELP);
        return true;
      case "reset":
        await this.reset();
        break;
      case "chaos":
        await this.setChaos(parsed.value);
        break;
      case "event":
        await this.randomEvent();
        break;
      case "scene":
        await this.sceneCheck(parsed.expected);
        break;
      case "ask":
        await this.askYesNo(parsed.question, parsed.likelihood);
        break;
      case "retreat":
        await this.submitTurn(buildRetreatPrompt(parsed.reason));
        break;
      case "acquire":
        await this.submitTurn(buildAcquirePrompt(parsed.verb, parsed.body));
        break;
      case "explain":
        await this.explain(parsed.question);
        break;
      case "end":
        await this.endCampaign(parsed.reason, parsed.summary);
        break;
      case "action":
        await this.submitTurn(parsed.text);
        break;
    }
    return this.#owner.error === null;
  }

  #note(kind: ClientNote["kind"], text: string): void {
    this.#owner.notes = [...this.#owner.notes, createClientNote(kind, text)];
  }

  #explanationNote(question: string, answer: string): void {
    this.#owner.notes = [...this.#owner.notes, createExplanationNote(question, answer)];
    saveOocNotes(this.#owner.activeSaveId, this.#owner.notes);
  }

  #oraclePreviewNote(question: string, outcome: OracleOutcome): void {
    this.#owner.notes = [...this.#owner.notes, createOraclePreviewNote(question, outcome)];
  }
}
