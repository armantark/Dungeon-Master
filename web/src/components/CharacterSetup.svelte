<!--
@component
CharacterSetup — pre-campaign character creation.

Why three paths plus a quiz step:
- Templates and scratch existed first; they handle "I want a known archetype"
  and "I want to fill the form myself" respectively.
- The assist path used to be a single textarea. That produced bland drafts
  because one sentence didn't pin the LLM to anything specific. Now the
  concept is the *seed* for an interview tailored to that concept, and
  the answers are what actually go into the draft prompt. The interview
  forces commitment in dimensions the LLM would otherwise softball:
  body/condition, what was lost, what is carried, who hunts you, the
  recurring sin.
- We always end in `edit` so the player can rewrite anything before
  finalizing — the LLM is a co-author here, not the source of truth.
-->
<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { game } from "../lib/store.svelte";
  import { blankCharacterDraft, deriveSetupMode } from "../lib/character";
  import {
    buildQuizAnswers,
    isQuizAnswered,
    type AnswerState,
    type SetupMode,
  } from "../lib/quiz";
  import type {
    CharacterQuiz,
    CharacterSheet,
    GameState,
  } from "../lib/types";
  import CampaignSeedEditor from "./CampaignSeedEditor.svelte";
  import CharacterEditor from "./CharacterEditor.svelte";
  import CharacterTemplateCard from "./CharacterTemplateCard.svelte";
  import LoadingPanel from "./LoadingPanel.svelte";

  type Props = { state: GameState };
  const { state: gs }: Props = $props();

  let mode: SetupMode = $state(untrack(() => deriveSetupMode(gs.campaign_status)));
  let templates: CharacterSheet[] = $state([]);
  let prompt = $state("");
  let quiz: CharacterQuiz | null = $state(null);
  let answers: Record<string, AnswerState> = $state({});
  let finalNote = $state("");
  let draft: CharacterSheet = $state(
    untrack(() => gs.character ?? blankCharacterDraft()),
  );

  $effect(() => {
    if (gs.campaign_status === "ready_to_start" || gs.campaign_status === "active") {
      draft = structuredClone(gs.character ?? draft);
      mode = deriveSetupMode(gs.campaign_status);
    }
  });

  onMount(() => {
    if (gs.campaign_status === "ready_to_start") {
      mode = "edit";
    }
  });

  async function loadTemplates(): Promise<void> {
    templates = await game.fetchCharacterTemplates();
    if (templates.length > 0) mode = "templates";
  }

  async function quickstart(template: CharacterSheet): Promise<void> {
    await game.finalizeCharacter(template);
    await game.startCampaign();
  }

  async function editTemplate(template: CharacterSheet): Promise<void> {
    const next = await game.generateCharacterDraft("template", undefined, template);
    draft = next ?? structuredClone(template);
    mode = "edit";
  }

  async function beginInterview(): Promise<void> {
    const trimmed = prompt.trim();
    if (trimmed === "") return;
    const next = await game.generateCharacterQuiz(trimmed);
    if (!next) return; // user cancelled or request errored — `game.error` carries it
    quiz = next;
    answers = {};
    finalNote = "";
    mode = "quiz";
  }

  function chooseOption(questionId: string, label: string): void {
    // Picking an MC option clears any "Other" text the player started.
    // The two are exclusive on purpose — letting both through would force
    // the LLM to disambiguate and that's exactly the kind of vague signal
    // the interview is meant to remove.
    answers = { ...answers, [questionId]: { selected: label, otherText: "" } };
  }

  function writeOther(questionId: string, text: string): void {
    answers = { ...answers, [questionId]: { selected: null, otherText: text } };
  }

  function goToReview(): void {
    if (quiz === null) return;
    if (!isQuizAnswered(quiz, answers)) return;
    mode = "review";
  }

  async function generateFromQuiz(): Promise<void> {
    if (quiz === null) return;
    const built = buildQuizAnswers(quiz, answers);
    const next = await game.generateQuizzedCharacterDraft(
      quiz.concept,
      built,
      finalNote.trim() || null,
    );
    if (!next) return;
    draft = next;
    mode = "edit";
  }

  async function saveDraft(): Promise<void> {
    await game.finalizeCharacter(draft);
  }

  async function saveAndStart(): Promise<void> {
    await game.finalizeCharacter(draft);
    await game.startCampaign();
  }
</script>

<section class="setup">
  <div class="intro iron">
    <div>
      <span class="kicker">Before The Campaign</span>
      <h2>Choose who enters the world.</h2>
    </div>
    <p>
      The world should grow around the character, not the other way around. Pick an
      archetypal survivor, start from scratch, or describe a concept and answer a
      short interview before the AI drafts you a sheet.
    </p>
  </div>

  <!--
    F-15: campaign-seed editor lives above the mode picker. Templates,
    the assist quiz, and the eventual `startCampaign` generation all
    read `state.campaign_seed`, so the player should commit setting +
    difficulty before generating drafts. Locked once the campaign is
    `active` / `ended` so re-rolling the seed never desyncs the
    generated world.
  -->
  <CampaignSeedEditor
    seed={gs.campaign_seed}
    locked={gs.campaign_status === "active" || gs.campaign_status === "ended"}
  />

  {#if mode === "choose"}
    <div class="modes">
      <button class="mode-card iron" onclick={loadTemplates} disabled={game.isLoading}>
        <span class="kicker">Templates</span>
        <strong>Generate archetypal survivors</strong>
        <span>See 4 AI-generated dark-fantasy templates and either quickstart or edit one.</span>
      </button>
      <button
        class="mode-card iron"
        disabled={game.isLoading}
        onclick={() => {
          draft = blankCharacterDraft();
          mode = "edit";
        }}
      >
        <span class="kicker">Scratch</span>
        <strong>Start with a blank sheet</strong>
        <span>Fill every field yourself and generate the campaign around that final version.</span>
      </button>
      <button
        class="mode-card iron"
        disabled={game.isLoading}
        onclick={() => (mode = "scratch")}
      >
        <span class="kicker">Assist</span>
        <strong>Describe a concept, answer an interview</strong>
        <span>The AI generates an interview tailored to your concept, then drafts the sheet.</span>
      </button>
    </div>

    {#if game.isLoading}
      <LoadingPanel
        title="Generating templates"
        subtitle="Asking the model for four archetypal dark-fantasy survivors."
        cancelLabel={game.cancelLabel}
        onCancel={() => game.cancelCurrentRequest()}
      />
    {/if}
  {:else if mode === "templates"}
    <div class="toolbar">
      <button class="ghost" onclick={() => (mode = "choose")} disabled={game.isLoading}>Back</button>
      <button class="ghost" onclick={loadTemplates} disabled={game.isLoading}>Regenerate templates</button>
    </div>
    {#if game.isLoading}
      <LoadingPanel
        title="Generating templates"
        subtitle="Composing four fresh survivors. This takes ~10–20 seconds."
        cancelLabel={game.cancelLabel}
        onCancel={() => game.cancelCurrentRequest()}
      />
    {:else}
      <div class="template-grid">
        {#each templates as template (template.name + template.archetype)}
          <CharacterTemplateCard
            {template}
            onEdit={editTemplate}
            onQuickstart={quickstart}
          />
        {/each}
      </div>
    {/if}
  {:else if mode === "scratch"}
    {#if game.isLoading}
      <LoadingPanel
        title="Composing your interview"
        subtitle="Reading your concept and writing 4–6 questions tailored to it."
        cancelLabel={game.cancelLabel}
        onCancel={() => game.cancelCurrentRequest()}
        showStream={true}
      />
    {:else}
      <div class="scratch iron">
        <label for="concept">Character concept</label>
        <textarea
          id="concept"
          rows="5"
          bind:value={prompt}
          placeholder="A plague-haunted scout who deserted the bone-grinders after hearing the engines whisper his dead sister's voice."
        ></textarea>
        <p class="muted small">
          The AI will use this to design a personalized interview. Be as specific as you like —
          culture, faith, era, vows, scars all carry through.
        </p>
        <div class="toolbar">
          <button class="ghost" onclick={() => (mode = "choose")}>Back</button>
          <button
            class="ghost"
            onclick={() => {
              draft = blankCharacterDraft();
              mode = "edit";
            }}
          >
            Skip AI and edit manually
          </button>
          <button onclick={beginInterview} disabled={prompt.trim() === ""}>
            Begin interview
          </button>
        </div>
      </div>
    {/if}
  {:else if mode === "quiz" && quiz !== null}
    {#if game.isLoading}
      <LoadingPanel
        title="Drafting your character"
        subtitle="Reading every answer and pinning the sheet to your concept."
        cancelLabel={game.cancelLabel}
        onCancel={() => game.cancelCurrentRequest()}
        showStream={true}
      />
    {:else}
      <div class="quiz">
        <div class="quiz__header iron">
          <span class="kicker">Interview · 1 of 2</span>
          <p class="muted">
            Concept: <em>{quiz.concept}</em>
          </p>
          <p class="muted small">
            Pick an option or write your own. Every answer commits a detail
            the AI is forbidden from contradicting later.
          </p>
        </div>

        {#each quiz.questions as question, idx (question.id)}
          {@const answerState = answers[question.id] ?? { selected: null, otherText: "" }}
          <fieldset class="question iron">
            <legend>
              <span class="kicker">Q{idx + 1}</span>
              <span class="prompt">{question.prompt}</span>
            </legend>

            <div class="options">
              {#each question.options as option (option.label)}
                <label class="option" class:selected={answerState.selected === option.label}>
                  <input
                    type="radio"
                    name={`q-${question.id}`}
                    value={option.label}
                    checked={answerState.selected === option.label}
                    onchange={() => chooseOption(question.id, option.label)}
                  />
                  <span>{option.label}</span>
                </label>
              {/each}

              <label
                class="option option--other"
                class:selected={answerState.selected === null && answerState.otherText !== ""}
              >
                <input
                  type="radio"
                  name={`q-${question.id}`}
                  checked={answerState.selected === null && answerState.otherText !== ""}
                  onchange={() => writeOther(question.id, answerState.otherText)}
                />
                <span>Other (write your own)</span>
              </label>

              {#if answerState.selected === null}
                <textarea
                  class="other-input"
                  rows="2"
                  placeholder="One short sentence in your character's voice."
                  value={answerState.otherText}
                  oninput={(event) =>
                    writeOther(question.id, (event.target as HTMLTextAreaElement).value)}
                ></textarea>
              {/if}
            </div>
          </fieldset>
        {/each}

        <div class="toolbar toolbar--end">
          <button class="ghost" onclick={() => (mode = "scratch")}>Back to concept</button>
          <button onclick={goToReview} disabled={!isQuizAnswered(quiz, answers)}>
            Continue to review
          </button>
        </div>
      </div>
    {/if}
  {:else if mode === "review" && quiz !== null}
    {#if game.isLoading}
      <LoadingPanel
        title="Drafting your character"
        subtitle="Reading every answer and pinning the sheet to your concept."
        cancelLabel={game.cancelLabel}
        onCancel={() => game.cancelCurrentRequest()}
        showStream={true}
      />
    {:else}
      <div class="review">
        <div class="review__header iron">
          <span class="kicker">Interview · 2 of 2</span>
          <p>
            <strong>Concept:</strong> {quiz.concept}
          </p>
        </div>

        <ol class="answers">
          {#each quiz.questions as question, idx (question.id)}
            {@const a = answers[question.id]}
            <li class="iron">
              <span class="kicker">Q{idx + 1}</span>
              <p class="prompt">{question.prompt}</p>
              <p class="answer">
                {a?.selected ?? a?.otherText ?? "(unanswered)"}
                {#if a !== undefined && a.selected === null && a.otherText !== ""}
                  <span class="muted small"> (your own)</span>
                {/if}
              </p>
            </li>
          {/each}
        </ol>

        <div class="iron extra">
          <label for="final-note" class="kicker as-label">Anything else? (optional)</label>
          <textarea
            id="final-note"
            rows="3"
            bind:value={finalNote}
            placeholder="A scar, a name, a habit — anything the AI must not skip."
          ></textarea>
        </div>

        <div class="toolbar toolbar--end">
          <button class="ghost" onclick={() => (mode = "quiz")}>Back to interview</button>
          <button onclick={generateFromQuiz}>Generate draft</button>
        </div>
      </div>
    {/if}
  {:else}
    <div class="toolbar">
      <button class="ghost" onclick={() => (mode = "choose")}>Change path</button>
      {#if gs.campaign_status === "ready_to_start"}
        <button class="ghost" onclick={() => void game.startCampaign()}>
          Start from saved draft
        </button>
      {/if}
    </div>
    <CharacterEditor character={draft} onChange={(next) => (draft = next)} />
    <div class="toolbar toolbar--end">
      <button class="ghost" onclick={saveDraft}>Save draft</button>
      <button onclick={saveAndStart}>Finalize and start campaign</button>
    </div>
    {#if game.isLoading}
      <LoadingPanel
        title="Generating opening scene"
        subtitle="Composing the world, threads, NPCs, and oracle word banks around this character."
        cancelLabel={game.cancelLabel}
        onCancel={() => game.cancelCurrentRequest()}
        showStream={true}
      />
    {/if}
  {/if}

  {#if game.error}
    <div class="error" role="alert">{game.error}</div>
  {/if}
</section>

<style>
  .setup {
    width: min(1100px, 100%);
    margin: 0 auto;
    padding: 1rem 1.2rem 1.5rem;
    display: grid;
    gap: 1rem;
  }
  .intro {
    padding: 1rem 1.1rem;
    display: grid;
    gap: 0.45rem;
  }
  .intro h2 {
    margin: 0.1rem 0 0;
    font-size: 1.45rem;
  }
  .intro p {
    margin: 0;
    max-width: 72ch;
    color: var(--paper-bone);
  }
  .modes,
  .template-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 0.9rem;
  }
  .mode-card {
    display: grid;
    gap: 0.35rem;
    text-align: left;
    padding: 1rem;
  }
  .mode-card strong {
    font-family: var(--font-display);
    font-size: 1.05rem;
    font-weight: 400;
    color: var(--paper-warm);
  }
  .mode-card span:last-child {
    color: var(--paper-shadow);
    font-size: 0.9rem;
    text-transform: none;
    letter-spacing: 0;
  }
  .toolbar {
    display: flex;
    gap: 0.7rem;
    flex-wrap: wrap;
  }
  .toolbar--end {
    justify-content: flex-end;
  }
  .scratch {
    padding: 1rem;
    display: grid;
    gap: 0.7rem;
  }
  .small {
    font-size: 0.85rem;
  }
  .muted {
    color: var(--paper-shadow);
    margin: 0;
  }

  /* Quiz */
  .quiz {
    display: grid;
    gap: 0.8rem;
  }
  .quiz__header {
    padding: 0.9rem 1rem;
    display: grid;
    gap: 0.3rem;
  }
  .question {
    padding: 0.8rem 1rem 1rem;
    border: var(--rule-hair);
    display: grid;
    gap: 0.6rem;
    margin: 0;
  }
  .question legend {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    padding: 0 0.4rem;
  }
  .question .prompt {
    font-family: var(--font-display);
    font-size: 1.05rem;
    color: var(--paper-warm);
  }
  .options {
    display: grid;
    gap: 0.4rem;
  }
  .option {
    display: flex;
    align-items: flex-start;
    gap: 0.6rem;
    padding: 0.5rem 0.7rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 30%, transparent);
    border-radius: 2px;
    cursor: pointer;
    background: color-mix(in oklab, var(--ink-deep) 80%, transparent);
  }
  .option:hover {
    border-color: var(--gold-tarnished);
  }
  .option.selected {
    border-color: var(--gold-bright);
    background: color-mix(in oklab, var(--gold-tarnished) 14%, var(--ink-deep) 86%);
  }
  .option input[type="radio"] {
    margin-top: 0.25rem;
  }
  .option--other {
    border-style: dashed;
  }
  .other-input {
    margin-top: 0.2rem;
  }

  /* Review */
  .review {
    display: grid;
    gap: 0.8rem;
  }
  .review__header {
    padding: 0.9rem 1rem;
    display: grid;
    gap: 0.2rem;
  }
  .answers {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.5rem;
  }
  .answers li {
    padding: 0.7rem 0.9rem;
    display: grid;
    gap: 0.2rem;
  }
  .answers .prompt {
    margin: 0;
    color: var(--paper-shadow);
    font-size: 0.95rem;
  }
  .answers .answer {
    margin: 0;
    color: var(--paper-warm);
    font-family: var(--font-display);
  }
  .extra {
    padding: 0.8rem 1rem;
    display: grid;
    gap: 0.4rem;
  }
  .as-label {
    margin: 0;
  }

  .error {
    padding: 0.7rem 1rem;
    border: 1px solid var(--rust-iron);
    background: color-mix(in oklab, var(--rust-blood) 22%, transparent);
    color: var(--paper-warm);
    font-family: var(--font-pixel);
    letter-spacing: 0.04em;
  }
</style>
