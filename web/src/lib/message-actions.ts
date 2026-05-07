// F-10 added the `ooc` speaker for the OOC explainer. Regenerate is
// gated on the canonical-narrative tail, so only `dm` messages can
// ever be regen targets — `ooc` answers are ephemeral and lack a
// backend event id to regenerate against.
export function canRegenerateMessage(
  kind: "dm" | "player" | "system" | "ooc",
  eventId: string,
  latestNarrativeId: string | null,
): boolean {
  return kind === "dm" && latestNarrativeId !== null && eventId === latestNarrativeId;
}
