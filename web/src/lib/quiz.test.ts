import { describe, expect, it } from "vitest";

import { buildQuizAnswers, isQuizAnswered, type AnswerState } from "./quiz";
import type { CharacterQuiz } from "./types";

const SAMPLE_QUIZ: CharacterQuiz = {
  concept: "A scarred deserter.",
  questions: [
    {
      id: "q_1",
      prompt: "What did you take?",
      options: [{ label: "A relic." }, { label: "A debt." }],
    },
    {
      id: "q_2",
      prompt: "Who is hunting you?",
      options: [{ label: "An order." }, { label: "Your dead." }],
    },
  ],
};

describe("isQuizAnswered", () => {
  it("requires every question to have a selection or non-empty other", () => {
    const answers: Record<string, AnswerState> = {
      q_1: { selected: "A relic.", otherText: "" },
    };
    // Why we treat undefined as unanswered: missing keys are the natural
    // shape Svelte produces when the player hasn't touched a question.
    expect(isQuizAnswered(SAMPLE_QUIZ, answers)).toBe(false);

    const filled: Record<string, AnswerState> = {
      q_1: { selected: "A relic.", otherText: "" },
      q_2: { selected: null, otherText: "  An order I cannot return to.  " },
    };
    expect(isQuizAnswered(SAMPLE_QUIZ, filled)).toBe(true);
  });

  it("rejects whitespace-only Other answers", () => {
    const answers: Record<string, AnswerState> = {
      q_1: { selected: "A relic.", otherText: "" },
      q_2: { selected: null, otherText: "    " },
    };
    expect(isQuizAnswered(SAMPLE_QUIZ, answers)).toBe(false);
  });
});

describe("buildQuizAnswers", () => {
  it("threads selected and Other answers into API payload shape", () => {
    const answers: Record<string, AnswerState> = {
      q_1: { selected: "A relic.", otherText: "" },
      q_2: { selected: null, otherText: "  My old company.  " },
    };

    const built = buildQuizAnswers(SAMPLE_QUIZ, answers);

    expect(built).toEqual([
      {
        question_id: "q_1",
        prompt: "What did you take?",
        value: "A relic.",
        is_other: false,
      },
      {
        question_id: "q_2",
        prompt: "Who is hunting you?",
        value: "My old company.",
        is_other: true,
      },
    ]);
  });

  it("preserves question order even when answers are added out of order", () => {
    const answers: Record<string, AnswerState> = {
      q_2: { selected: "Your dead.", otherText: "" },
      q_1: { selected: "A debt.", otherText: "" },
    };
    const built = buildQuizAnswers(SAMPLE_QUIZ, answers);
    expect(built.map((a) => a.question_id)).toEqual(["q_1", "q_2"]);
  });
});
