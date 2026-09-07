import assert from "node:assert/strict";
import test from "node:test";

import { createNotionDesktopAdapter, extractVisibleResult, observeNotionAX } from "../scripts/notion-desktop-adapter.mjs";

const expected = Object.freeze({
  tabTitle: "Notion AI",
  model: "GPT-5.6 Sol",
  effort: "high",
  prompt: "Explain the release gate.\nKeep the answer concise.",
});

function actualAx({
  title = "Notion AI",
  model = "GPT-5.6 Sol",
  effort = "높음",
  prompt = "",
  submitDisabled = true,
  composer = true,
  secondContent = false,
  generating = false,
  response = "",
  userMessage = "",
  completed = false,
  virtualized = false,
  globalVirtualized = false,
  codeCompletionText = "",
} = {}) {
  const [firstPrompt = "", ...continuedPrompt] = prompt.split("\n");
  return [
    `Window: "${title}", App: Notion.`,
    `0 표준 윈도우 ${title}, Secondary Actions: Raise`,
    `\t1 container ${title}`,
    "\t\t2 container",
    "\t\t\t3 HTML 콘텐츠 Tab Bar, URL: file:///Applications/Notion.app/Contents/Resources/app.asar/.webpack/renderer/tabs/index.html",
    "\t\t\t\t4 container",
    "\t\t\t\t\t11 버튼 Notion AI",
    "\t\t\t\t\t23 버튼 새 탭",
    `\t\t\t24 HTML 콘텐츠 ${title}, URL: app.notion.com/ai?spaceId=fixture`,
    "\t\t\t\t147 container",
    composer ? `\t\t\t\t\t157 텍스트 엔트리 영역 (settable)${firstPrompt ? ` ${firstPrompt}` : ""}` : "",
    ...(composer ? continuedPrompt : []),
    `\t\t\t\t\t162 팝업 버튼 노력 변경, 현재 ${effort}`,
    `\t\t\t\t\t163 팝업 버튼 ${model}`,
    `\t\t\t\t\t166 버튼${submitDisabled ? " (disabled)" : ""} AI 메시지 제출하기`,
    generating ? "\t\t\t\t\t215 버튼 AI 메시지 중지하기" : "",
    response ? "\t\t\t\t\t300 container response" : "",
    ...response.split("\n").filter(Boolean).map((line, index) => `\t\t\t\t\t\t${301 + index} 텍스트 ${line}`),
    response ? "\t\t\t\t\t468 버튼 답변 복사" : "",
    completed ? "\t\t\t\t\t483 텍스트 Notion AI 작업이 완료되었습니다." : "",
    virtualized ? "\t\t\t\t\t170 container (showing 161-261 of 261 items)" : "",
    userMessage ? "\t\t\t\t\t500 container user message" : "",
    ...userMessage.split("\n").filter(Boolean).map((line, index) => `\t\t\t\t\t\t${501 + index} 텍스트 ${line}`),
    codeCompletionText ? "\t\t\t\t\t600 container code" : "",
    codeCompletionText ? `\t\t\t\t\t\t601 텍스트 ${codeCompletionText}` : "",
    secondContent ? `\t\t\t25 HTML 콘텐츠 ${title}, URL: app.notion.com/ai?spaceId=second-copy` : "",
    globalVirtualized ? "999 container (showing 1-999 of 999 items)" : "",
  ].filter(Boolean).join("\n");
}

function fakeApp(states, { clickErrorAt } = {}) {
  const clicks = [];
  const pastes = [];
  let read = 0;
  return {
    clicks,
    pastes,
    async getAXState(options) {
      assert.deepEqual(options, { emit: false, disableDiffing: true });
      return states[Math.min(read++, states.length - 1)];
    },
    async click(index) {
      clicks.push(index);
      if (index === clickErrorAt) throw new Error("click transport lost");
    },
    async paste(text, options) {
      pastes.push([text, options]);
    },
    async pressKey() {},
  };
}

test("recognizes the supplied Korean app.notion.com AX shape before paste", () => {
  const observed = observeNotionAX(actualAx(), expected, { allowDisabledSend: true });
  assert.equal(observed.status, "ready");
  assert.equal(observed.input.index, 157);
  assert.equal(observed.send.index, 166);
});

test("does not submit for ambiguous same-window Notion HTML contents", async () => {
  const app = fakeApp([actualAx({ secondContent: true })]);
  const prepared = await createNotionDesktopAdapter(app).prepare(expected);
  assert.equal(prepared.status, "ambiguous_target");
  assert.deepEqual(app.clicks, []);
});

test("does not submit when full multiline prompt readback mismatches", async () => {
  const app = fakeApp([
    actualAx(), actualAx(), actualAx(), actualAx({ prompt: "Explain the release gate.\nKeep the answer", submitDisabled: false }),
  ]);
  const adapter = createNotionDesktopAdapter(app);
  const result = await adapter.send(await adapter.prepare(expected));
  assert.equal(result.status, "prompt_mismatch");
  assert.deepEqual(app.clicks, [157]);
  assert.deepEqual(app.pastes, [[expected.prompt, { format: "text" }]]);
});

test("does not submit on model mismatch", async () => {
  const app = fakeApp([actualAx({ model: "GPT-5.6 Luna" })]);
  const result = await createNotionDesktopAdapter(app).prepare(expected);
  assert.equal(result.status, "settings_mismatch");
  assert.deepEqual(app.clicks, []);
});

test("preserves an existing user draft without clicking or pasting", async () => {
  const app = fakeApp([actualAx({ prompt: "unfinished user draft" })]);
  assert.equal((await createNotionDesktopAdapter(app).prepare(expected)).status, "draft_present");
  assert.deepEqual(app.clicks, []);
  assert.deepEqual(app.pastes, []);
});

test("stops when a user draft appears after preparation", async () => {
  const app = fakeApp([actualAx(), actualAx({ prompt: "new user draft" })]);
  const adapter = createNotionDesktopAdapter(app);
  assert.equal((await adapter.send(await adapter.prepare(expected))).status, "draft_present");
  assert.deepEqual(app.pastes, []);
});

test("never prepares a new prompt during an existing generation", async () => {
  const app = fakeApp([actualAx({ generating: true })]);
  assert.equal((await createNotionDesktopAdapter(app).prepare(expected)).status, "busy");
  assert.deepEqual(app.clicks, []);
});

test("a submit click error is uncertain and consumes its prepared token", async () => {
  const app = fakeApp([
    actualAx(), actualAx(), actualAx(), actualAx({ prompt: expected.prompt, submitDisabled: false }),
  ], { clickErrorAt: 166 });
  const adapter = createNotionDesktopAdapter(app);
  const prepared = await adapter.prepare(expected);
  assert.equal((await adapter.send(prepared)).status, "uncertain_send");
  assert.equal((await adapter.send(prepared)).status, "invalid_preparation");
  assert.deepEqual(app.clicks, [157, 166]);
});

test("does not assume a successful submit click sent anything without post-click evidence", async () => {
  const ready = actualAx({ prompt: expected.prompt, submitDisabled: false });
  const app = fakeApp([actualAx(), actualAx(), actualAx(), ready, ready]);
  const adapter = createNotionDesktopAdapter(app);
  assert.equal((await adapter.send(await adapter.prepare(expected))).status, "uncertain_send");
  assert.deepEqual(app.clicks, [157, 166]);
});

test("does not report sent when post-click composer is missing", async () => {
  const app = fakeApp([
    actualAx(), actualAx(), actualAx(), actualAx({ prompt: expected.prompt, submitDisabled: false }), actualAx({ composer: false }),
  ]);
  const adapter = createNotionDesktopAdapter(app);
  assert.equal((await adapter.send(await adapter.prepare(expected))).status, "uncertain_send");
});

test("does not report sent when the disabled submit remains with an unchanged prompt", async () => {
  const post = actualAx({ prompt: expected.prompt, submitDisabled: true });
  const app = fakeApp([actualAx(), actualAx(), actualAx(), actualAx({ prompt: expected.prompt, submitDisabled: false }), post]);
  const adapter = createNotionDesktopAdapter(app);
  assert.equal((await adapter.send(await adapter.prepare(expected))).status, "uncertain_send");
});

test("an enabled exact Korean stop button is post-click send evidence", async () => {
  const post = actualAx({ prompt: expected.prompt, submitDisabled: true, generating: true });
  const app = fakeApp([actualAx(), actualAx(), actualAx(), actualAx({ prompt: expected.prompt, submitDisabled: false }), post]);
  const adapter = createNotionDesktopAdapter(app);
  assert.equal((await adapter.send(await adapter.prepare(expected))).status, "sent");
});

test("virtualized output is partial and never complete", () => {
  const result = extractVisibleResult(actualAx({ response: "Visible beginning only", virtualized: true }), expected);
  assert.equal(result.status, "partial");
  assert.equal(result.complete, false);
  assert.equal(result.text, "Visible beginning only");
});

test("global AX virtualization forces partial even outside the parsed Notion HTML", () => {
  const result = extractVisibleResult(actualAx({ response: "Visible result", completed: true, globalVirtualized: true }), expected);
  assert.equal(result.status, "partial");
  assert.equal(result.complete, false);
});

test("completion requires the exact UI marker, not words inside the answer", () => {
  assert.equal(extractVisibleResult(actualAx({ response: "The task is completed." }), expected).status, "incomplete");
  assert.equal(extractVisibleResult(actualAx({ response: "The task is completed.", completed: true }), expected).status, "completed");
});

test("completion-looking text inside code cannot certify completion", () => {
  const result = extractVisibleResult(actualAx({ response: "Visible answer", codeCompletionText: "Notion AI 작업이 완료되었습니다." }), expected);
  assert.equal(result.status, "incomplete");
});

test("AX-only code output remains partial even with completion markers", () => {
  const ax = actualAx({ response: "if ready:\n    pass", completed: true })
    .replace("300 container response", "300 container response code");
  assert.equal(extractVisibleResult(ax, expected).status, "partial");
});

test("creates a new top-bar tab through its nested Tab Bar and starts fresh chat", async () => {
  const afterTab = actualAx()
    .replace("\t\t\t\t\t23 버튼 새 탭", "\t\t\t\t\t23 버튼 새 탭\n\t\t\t\t\t12 버튼 Notion AI 2")
    .concat("\n\t\t\t\t\t200 버튼 새 채팅 시작");
  const started = `${afterTab}\n\t\t\t26 HTML 콘텐츠 새 채팅, URL: app.notion.com/ai?spaceId=fresh`;
  const app = fakeApp([actualAx(), afterTab, started]);
  const result = await createNotionDesktopAdapter(app).createDistinctTab();
  assert.equal(result.status, "new_chat_started");
  assert.deepEqual(app.clicks, [23, 200]);
});

test("tab creation no-op is unverified rather than success", async () => {
  const app = fakeApp([actualAx(), actualAx()]);
  const result = await createNotionDesktopAdapter(app).createDistinctTab();
  assert.equal(result.status, "unverified");
  assert.deepEqual(app.clicks, [23]);
});

test("changed ephemeral AX indices do not prove a new tab", async () => {
  const after = actualAx().replace("11 버튼", "12 버튼").concat("\n\t\t\t\t\t200 버튼 새 채팅 시작");
  const started = `${after}\n\t\t\t26 HTML 콘텐츠 새 채팅, URL: app.notion.com/ai?spaceId=fresh`;
  const app = fakeApp([actualAx(), after, started]);
  assert.equal((await createNotionDesktopAdapter(app).createDistinctTab()).status, "unverified");
  assert.deepEqual(app.clicks, [23]);
});
