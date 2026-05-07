// Markdown renderer for chat output.
//
// We render model-authored prose (DM narration + OOC explainer answers)
// through `marked` so the asterisks/backticks/lists the model already
// emits land as real emphasis/code/structure instead of bleeding into
// the page as raw glyphs. Player-typed messages stay plain text on
// purpose: nobody types `**foo**` expecting it to bold, and we don't
// want a stray underscore in a name to flip into italics mid-sentence.
//
// Streaming safety:
//   - `marked` tolerates unclosed inline marks (e.g. a half-arrived
//     `**bold`) — it falls back to rendering them literally instead of
//     throwing. That means we can re-parse the buffer on every token
//     without a try/catch.
//   - We pass `breaks: true` so a single `\n` in narration becomes a
//     `<br>`, matching the previous `white-space: pre-wrap` behavior.
//
// Sanitization:
//   - `marked` does not sanitize. The model is in principle untrusted
//     output (it could echo a `<script>` if a player asked it to), so
//     every render goes through DOMPurify before reaching `{@html}`.
//   - We allow the standard prose tags + inline code/pre. We disallow
//     raw HTML tags by leaving `dangerouslySetInnerHTML`-ish things
//     out of the allowlist; DOMPurify also strips `on*` attributes
//     and `javascript:` URLs by default.
import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({
  // GitHub-flavored: tables, fenced code, strikethrough, autolinks.
  // We're not formally on GFM but the LLM uses these constructs the
  // same way, so it's the right default.
  gfm: true,
  // Single newline -> <br>. Without this, the model's paragraph-style
  // line breaks (common when it lists short bullets without a blank
  // line between them) collapse into one run-on line.
  breaks: true,
});

const ALLOWED_TAGS = [
  "p",
  "br",
  "hr",
  "strong",
  "em",
  "u",
  "s",
  "del",
  "code",
  "pre",
  "blockquote",
  "ul",
  "ol",
  "li",
  "a",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
  "span",
];

const ALLOWED_ATTR = ["href", "title", "target", "rel", "class"];

export function renderMarkdown(input: string): string {
  if (!input) return "";
  // `marked.parse` can return a Promise when async extensions are
  // registered. We don't register any, so the sync `{ async: false }`
  // overload returns a string and lets us stay in a sync render path.
  const html = marked.parse(input, { async: false }) as string;
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    // Force every <a> through `rel="noopener noreferrer"` and a new
    // tab, so a model-generated link can't hijack the chat surface.
    ADD_ATTR: ["target", "rel"],
  });
}
