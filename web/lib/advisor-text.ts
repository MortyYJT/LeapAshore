/**
 * The advisor's reply as structure: paragraphs, lists and the few inline marks a chat model writes.
 *
 * The reply is model text, so nothing in it is treated as HTML. It is cut into plain pieces which the
 * page renders as elements; a link is kept only when it is http(s). A `[2]` is a reference to the
 * second source card of the same turn.
 */

export type Inline =
  | { type: "text"; text: string }
  | { type: "strong"; text: string }
  | { type: "code"; text: string }
  | { type: "link"; text: string; href: string }
  | { type: "cite"; n: number };

export type TextBlock =
  | { type: "paragraph"; lines: Inline[][] }
  | { type: "heading"; content: Inline[] }
  | { type: "list"; ordered: boolean; items: Inline[][]; /** The number each item was written with. */ numbers?: number[] };

// In order: **bold**, `code`, [label](url), a bare url, [n].
const INLINE = /\*\*([^*\n]+)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>"'，。；、）】]+)|\[(\d{1,2})\]/g;
// Punctuation that ends a sentence, not a url.
const TRAILING = /[.,;:!?)\]]+$/;

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const push = (piece: string) => {
    if (!piece) return;
    const last = out.at(-1);
    if (last?.type === "text") last.text += piece;
    else out.push({ type: "text", text: piece });
  };
  let at = 0;
  for (const match of text.matchAll(INLINE)) {
    push(text.slice(at, match.index));
    at = match.index + match[0].length;
    if (match[1] !== undefined) out.push({ type: "strong", text: match[1] });
    else if (match[2] !== undefined) out.push({ type: "code", text: match[2] });
    else if (match[3] !== undefined) out.push({ type: "link", text: match[3], href: match[4] });
    else if (match[5] !== undefined) {
      const tail = match[5].match(TRAILING)?.[0] ?? "";
      const href = tail ? match[5].slice(0, -tail.length) : match[5];
      out.push({ type: "link", text: href, href });
      push(tail);
    } else out.push({ type: "cite", n: Number(match[6]) });
  }
  push(text.slice(at));
  return out;
}

const BULLET = /^\s*[-*•]\s+(.*)$/;
// A reply's figures must come through as written, so a line only counts as a list item when its
// number cannot be part of the sentence: "1. " and "1) " need the space ("6.5 分" is not item 6), and
// "1、" must not run into another number ("9、10 月截止" lists two months).
const NUMBERED = /^\s*(\d{1,2})(?:[.)]\s+|、\s*(?!\d))(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;

export function parseAnswer(text: string): TextBlock[] {
  const blocks: TextBlock[] = [];
  let paragraph: Inline[][] = [];
  const flush = () => {
    if (paragraph.length) blocks.push({ type: "paragraph", lines: paragraph });
    paragraph = [];
  };
  for (const line of text.replace(/\r\n?/g, "\n").split("\n")) {
    if (!line.trim()) {
      flush();
      continue;
    }
    const heading = line.match(HEADING);
    if (heading) {
      flush();
      blocks.push({ type: "heading", content: parseInline(heading[1].replace(/\s*#+\s*$/, "")) });
      continue;
    }
    const bullet = line.match(BULLET);
    const numbered = bullet ? null : line.match(NUMBERED);
    if (bullet || numbered) {
      flush();
      const item = parseInline(bullet ? bullet[1] : numbered![2]);
      const last = blocks.at(-1);
      if (bullet) {
        if (last?.type === "list" && !last.ordered) last.items.push(item);
        else blocks.push({ type: "list", ordered: false, items: [item] });
      } else {
        // The item keeps the number the reply gave it, whatever the list it lands in.
        const n = Number(numbered![1]);
        if (last?.type === "list" && last.ordered) {
          last.items.push(item);
          last.numbers!.push(n);
        } else blocks.push({ type: "list", ordered: true, items: [item], numbers: [n] });
      }
      continue;
    }
    paragraph.push(parseInline(line.trim()));
  }
  flush();
  return blocks;
}
