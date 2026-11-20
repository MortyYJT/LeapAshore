import assert from "node:assert/strict";
import { test } from "node:test";

import { parseAnswer, parseInline } from "./advisor-text.ts";

test("plain sentences stay one paragraph, line by line", () => {
  assert.deepEqual(parseAnswer("第一句。\n第二句。\n\n另一段。"), [
    { type: "paragraph", lines: [[{ type: "text", text: "第一句。" }], [{ type: "text", text: "第二句。" }]] },
    { type: "paragraph", lines: [[{ type: "text", text: "另一段。" }]] },
  ]);
});

test("a source number becomes a reference to that source", () => {
  assert.deepEqual(parseInline("语言要求是 IELTS 6.5[1][2]。"), [
    { type: "text", text: "语言要求是 IELTS 6.5" },
    { type: "cite", n: 1 },
    { type: "cite", n: 2 },
    { type: "text", text: "。" },
  ]);
  // A bracket that is not a source number is left as written.
  assert.deepEqual(parseInline("见 [附件] 和 [123]"), [{ type: "text", text: "见 [附件] 和 [123]" }]);
});

test("bold, code and links are the only marks read", () => {
  assert.deepEqual(parseInline("**截止** 用 `set_status`，见 [官网](https://example.edu/a)"), [
    { type: "strong", text: "截止" },
    { type: "text", text: " 用 " },
    { type: "code", text: "set_status" },
    { type: "text", text: "，见 " },
    { type: "link", text: "官网", href: "https://example.edu/a" },
  ]);
});

test("a bare url is a link, without the punctuation after it", () => {
  assert.deepEqual(parseInline("请以官网为准：https://example.edu/apply。下一句"), [
    { type: "text", text: "请以官网为准：" },
    { type: "link", text: "https://example.edu/apply", href: "https://example.edu/apply" },
    { type: "text", text: "。下一句" },
  ]);
  assert.deepEqual(parseInline("(https://example.edu/a?x=1)."), [
    { type: "text", text: "(" },
    { type: "link", text: "https://example.edu/a?x=1", href: "https://example.edu/a?x=1" },
    { type: "text", text: ")." },
  ]);
});

test("a link that is not http is not a link", () => {
  assert.deepEqual(parseInline("[点我](javascript:alert(1))"), [{ type: "text", text: "[点我](javascript:alert(1))" }]);
  assert.deepEqual(parseInline("<img src=x onerror=alert(1)>"), [{ type: "text", text: "<img src=x onerror=alert(1)>" }]);
});

test("lists and headings are read by their first characters", () => {
  assert.deepEqual(parseAnswer("## 材料\n- 成绩单\n- **推荐信** 两封\n\n1. 先查日期\n2、再备材料\n结论。"), [
    { type: "heading", content: [{ type: "text", text: "材料" }] },
    { type: "list", ordered: false, items: [[{ type: "text", text: "成绩单" }], [{ type: "strong", text: "推荐信" }, { type: "text", text: " 两封" }]] },
    { type: "list", ordered: true, items: [[{ type: "text", text: "先查日期" }], [{ type: "text", text: "再备材料" }]], numbers: [1, 2] },
    { type: "paragraph", lines: [[{ type: "text", text: "结论。" }]] },
  ]);
});

test("a sentence that opens with a figure keeps the figure", () => {
  for (const sentence of ["6.5 分是总分要求。", "9、10 月截止。", "80、85 分分别是两类院校的要求。"]) {
    assert.deepEqual(parseAnswer(sentence), [{ type: "paragraph", lines: [[{ type: "text", text: sentence }]] }]);
  }
});

test("a numbered item keeps the number it was written with", () => {
  assert.deepEqual(parseAnswer("先说第二点：\n2. 语言成绩\n\n另外：\n5、推荐信"), [
    { type: "paragraph", lines: [[{ type: "text", text: "先说第二点：" }]] },
    { type: "list", ordered: true, items: [[{ type: "text", text: "语言成绩" }]], numbers: [2] },
    { type: "paragraph", lines: [[{ type: "text", text: "另外：" }]] },
    { type: "list", ordered: true, items: [[{ type: "text", text: "推荐信" }]], numbers: [5] },
  ]);
});

test("a mark still being typed is shown as it is until it closes", () => {
  assert.deepEqual(parseInline("这是 **还没写完"), [{ type: "text", text: "这是 **还没写完" }]);
  assert.deepEqual(parseAnswer(""), []);
});
