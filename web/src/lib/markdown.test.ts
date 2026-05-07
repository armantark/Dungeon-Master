// @vitest-environment jsdom
//
// DOMPurify needs a DOM. The rest of the suite runs in plain node;
// the env directive here is scoped to this file so we don't pay for
// jsdom in unrelated tests.
import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./markdown";

describe("renderMarkdown", () => {
  it("returns the empty string for empty input", () => {
    expect(renderMarkdown("")).toBe("");
  });

  it("renders bold and italic emphasis", () => {
    const html = renderMarkdown("This is **bold** and *italic*.");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<em>italic</em>");
  });

  it("renders bullet lists", () => {
    const html = renderMarkdown("- alpha\n- beta\n- gamma");
    expect(html).toContain("<ul>");
    expect(html).toContain("<li>alpha</li>");
    expect(html).toContain("<li>gamma</li>");
  });

  it("renders inline code with backticks", () => {
    const html = renderMarkdown("Use `\"active\": false` to disable.");
    expect(html).toContain('<code>"active": false</code>');
  });

  it("converts a single newline into a <br> so list-style narration breaks survive", () => {
    // The model often emits "Right now:\n- foo\n- bar" without a
    // blank separator; without `breaks: true` this collapses into a
    // single line. We anchor that behavior here.
    const html = renderMarkdown("first\nsecond");
    expect(html).toMatch(/first<br\s*\/?>\s*second/);
  });

  it("strips raw HTML tags that are not in the allowlist", () => {
    // Defense in depth: even if the model echoes a script tag, the
    // sanitizer must drop it before {@html} sees it.
    const html = renderMarkdown("<script>alert(1)</script>hello");
    expect(html).not.toContain("<script");
    expect(html).toContain("hello");
  });

  it("strips event-handler attributes from any rendered tag", () => {
    const html = renderMarkdown('[click](javascript:alert(1) "x")');
    expect(html).not.toContain("javascript:");
  });

  it("tolerates an unclosed bold mid-stream without throwing", () => {
    // Streaming partials arrive with dangling marks. The renderer
    // must fall back to literal output instead of crashing — that's
    // the whole reason we re-parse on every token.
    expect(() => renderMarkdown("the door is **half")).not.toThrow();
    const html = renderMarkdown("the door is **half");
    expect(html).toContain("the door is");
  });
});
