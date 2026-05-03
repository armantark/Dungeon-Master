export function canRegenerateMessage(
  kind: "dm" | "player" | "system",
  eventId: string,
  latestNarrativeId: string | null,
): boolean {
  return kind === "dm" && latestNarrativeId !== null && eventId === latestNarrativeId;
}
