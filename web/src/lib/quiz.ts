// Pure helpers for the assist-mode interview.
//
// We keep these out of the Svelte component because they're easier to
// unit-test in isolation, and because the conversion from the player's
// runes-tracked answer map to the API payload is the kind of glue logic
// that historically attracts off-by-ones (lost questions, blank "Other"
// strings, mis-flagged is_other).

import type { CharacterQuiz, CharacterQuizAnswer } from "./types";

// Mirrors the local Svelte state in CharacterSetup. `selected` and
// `otherText` are exclusive: a non-null `selected` means the player
// took an option as written; a null `selected` with non-empty
// `otherText` means they wrote their own.
export interface AnswerState {
  selected: string | null;
  otherText: string;
}

// Re-export from character.ts so consumers that already import from quiz.ts
// don't have to learn a second module path. SetupMode lives with character
// helpers because it's the broader setup state machine, not a quiz concept.
export type { SetupMode } from "./character";

export function isQuizAnswered(
  quiz: CharacterQuiz,
  answers: Record<string, AnswerState>,
): boolean {
  return quiz.questions.every((question) => {
    const a = answers[question.id];
    if (a === undefined) return false;
    if (a.selected !== null && a.selected !== "") return true;
    return a.otherText.trim() !== "";
  });
}

export function buildQuizAnswers(
  quiz: CharacterQuiz,
  answers: Record<string, AnswerState>,
): CharacterQuizAnswer[] {
  return quiz.questions.map((question) => {
    const a = answers[question.id] ?? { selected: null, otherText: "" };
    if (a.selected !== null && a.selected !== "") {
      return {
        question_id: question.id,
        prompt: question.prompt,
        value: a.selected,
        is_other: false,
      };
    }
    return {
      question_id: question.id,
      prompt: question.prompt,
      value: a.otherText.trim(),
      is_other: true,
    };
  });
}
