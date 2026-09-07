/**
 * A deliberately small injected adapter for the Notion desktop AX surface.
 *
 * The host supplies App.  This module imports no desktop, browser, or network
 * API and keeps only ephemeral, in-process retry guards.
 */

const AX_OPTIONS = Object.freeze({ emit: false, disableDiffing: true });
const WINDOW_ROLE = /(?:^|[^a-z])(?:ax)?window(?:[^a-z]|$)/i;
const HTML_ROLE = /(?:web(?:\s|-)?(?:area|content)|html(?:\s|-)?content|document)/i;
const INPUT_ROLE = /(?:text(?:\s|-)?(?:field|area|box)|editable|textentry)/i;
const BUTTON_ROLE = /(?:button)/i;
const HIDDEN = /\b(?:hidden|invisible|offscreen|ignored)\b|\bvisible\s*[:=]\s*false\b/i;
const ACTIVE = /\b(?:active|focused|selected|current)\s*[:=]\s*(?:true|1)\b/i;
const DISABLED = /\bdisabled\b|\benabled\s*[:=]\s*false\b/i;
const STOP = /^AI 메시지 중지하기$/;
const COPY = /^(?:답변 복사|Copy)$/;
const SEND = /^(?:send|submit|보내기|전송|AI 메시지 제출하기)$/i;
const NEW_CHAT = /^새 채팅 시작$/;
const TAB_ADD = /^(?:\+|new tab|새 탭|add tab)$/i;
const ERROR = /\b(?:error|failed|failure)\b|(?:오류|실패)/i;
const TRUNCATED = /\(\s*showing\b[^)]*\)|\b(?:truncated|show more|continue reading)\b|(?:더 보기|계속 보기)/i;
const RESPONSE = /(?:assistant|ai (?:response|answer|message)|response|answer|응답|답변)/i;

function clean(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function quotedValues(value) {
  return [...String(value).matchAll(/(["'])(.*?)\1/g)].map((match) => clean(match[2])).filter(Boolean);
}

function nodeText(node) {
  return clean([...new Set([node.name, node.value, ...quotedValues(node.raw)].filter(Boolean))].join(" "));
}

function roleFrom(raw) {
  if (/표준 윈도우/.test(raw)) return "Window";
  if (/HTML 콘텐츠/.test(raw)) return "HTMLContent";
  if (/팝업 버튼/.test(raw)) return "PopupButton";
  if (/텍스트 엔트리 영역/.test(raw)) return "TextEntry";
  if (/버튼/.test(raw)) return "Button";
  if (/텍스트/.test(raw)) return "StaticText";
  if (/\bcontainer\b/i.test(raw)) return "Group";
  const match = raw.match(/\b(?:AX)?(Window|WebArea|WebContent|HTMLContent|Document|TextField|TextArea|TextBox|Editable|Button|TabBar|Group|StaticText|Label|Article)\b/i);
  return match ? match[1] : "";
}

function indexFrom(raw) {
  const numbered = raw.match(/^\s*(?:\[(\d+)\]|(\d+)(?=\s|[:.]))/);
  const named = raw.match(/\b(?:index|axindex)\s*[:=]\s*["']?(\d+)/i);
  return Number(numbered?.[1] ?? numbered?.[2] ?? named?.[1] ?? NaN);
}

function metadataFrom(raw) {
  const value = (key) => raw.match(new RegExp(`\\b${key}\\s*[:=]\\s*["']([^"']*)["']`, "i"))?.[1]
    ?? raw.match(new RegExp(`\\b${key}\\s*[:=]\\s*([^,;\\]]+)`, "i"))?.[1];
  const korean = raw.match(/(?:표준 윈도우|HTML 콘텐츠|팝업 버튼|텍스트 엔트리 영역|버튼|텍스트|container)\s+(.*)$/i)?.[1] ?? "";
  const koreanLabel = korean
    .replace(/^\(disabled\)\s*/i, "")
    .replace(/^\(settable\)\s*/i, "")
    .replace(/,\s*(?:URL|현재|Secondary Actions)\s*:.+$/i, "")
    .trim();
  const declaredValue = value("value") ?? value("text");
  return {
    name: value("name") ?? value("title") ?? (koreanLabel || quotedValues(raw)[0] || ""),
    value: declaredValue ?? (/텍스트 엔트리 영역/.test(raw) ? koreanLabel : ""),
    url: value("url") ?? raw.match(/https?:\/\/[^\s,\])"']+/i)?.[0] ?? "",
  };
}

function parseJsonAx(value) {
  const add = (entry, parent, nodes) => {
    if (!entry || typeof entry !== "object") return;
    const raw = JSON.stringify(entry);
    const node = {
      raw,
      role: clean(entry.role ?? entry.axRole ?? entry.type),
      index: Number(entry.index ?? entry.axIndex ?? NaN),
      name: clean(entry.name ?? entry.title ?? entry.label),
      value: String(entry.value ?? entry.text ?? ""),
      url: clean(entry.url ?? entry.URL),
      parent,
      children: [],
    };
    if (parent) parent.children.push(node);
    nodes.push(node);
    for (const child of entry.children ?? entry.nodes ?? []) add(child, node, nodes);
  };
  const nodes = [];
  add(value, null, nodes);
  return nodes;
}

/** Parse either JSON AX trees or the indented text returned by getAXState. */
export function parseAX(ax) {
  const source = String(ax ?? "");
  try {
    const parsed = JSON.parse(source);
    if (parsed && typeof parsed === "object") return parseJsonAx(parsed);
  } catch {
    // Text AX is the normal injected form.
  }

  const nodes = [];
  const stack = [];
  for (const rawLine of source.split(/\r?\n/)) {
    if (!rawLine.trim()) continue;
    const indent = rawLine.match(/^\s*/)[0].length;
    const raw = rawLine.trim();
    const role = roleFrom(raw);
    if (!role) {
      const previous = stack.at(-1)?.node;
      if (previous && (INPUT_ROLE.test(previous.role) || /statictext/i.test(previous.role))) {
        previous.value = `${previous.value}\n${rawLine}`;
        previous.raw = `${previous.raw}\n${rawLine}`;
      }
      continue;
    }
    if (/^Window:\s*/i.test(raw) && !Number.isInteger(indexFrom(raw))) continue;
    while (stack.length && stack.at(-1).indent >= indent) stack.pop();
    const parent = stack.at(-1)?.node ?? null;
    const metadata = metadataFrom(raw);
    const node = {
      raw,
      role,
      index: indexFrom(raw),
      name: clean(metadata.name),
      value: metadata.value,
      url: clean(metadata.url),
      parent,
      children: [],
    };
    if (parent) parent.children.push(node);
    nodes.push(node);
    stack.push({ indent, node });
  }
  return nodes;
}

function isDescendant(node, ancestor) {
  for (let cursor = node; cursor; cursor = cursor.parent) if (cursor === ancestor) return true;
  return false;
}

function isVisible(node) {
  for (let cursor = node; cursor; cursor = cursor.parent) if (HIDDEN.test(cursor.raw)) return false;
  return true;
}

function isActive(node) {
  for (let cursor = node; cursor; cursor = cursor.parent) if (ACTIVE.test(cursor.raw)) return true;
  return false;
}

function isEnabled(node) {
  return isVisible(node) && !DISABLED.test(node.raw);
}

function exact(node, label) {
  const text = nodeText(node);
  return text === label || quotedValues(node.raw).includes(label);
}

function contentNodes(nodes, content) {
  return nodes.filter((node) => isDescendant(node, content) && isVisible(node));
}

function notionChatUrl(url) {
  try {
    const parsed = new URL(/^https?:\/\//i.test(url) ? url : `https://${url}`);
    return /^(?:app\.)?notion\.com$/i.test(parsed.hostname) && /\/(?:chat|ai)(?:\/|$)/i.test(parsed.pathname)
      || /(^|\.)notion\.so$/i.test(parsed.hostname) && /\/(?:chat|ai)(?:\/|$)/i.test(parsed.pathname);
  } catch {
    return false;
  }
}

function exactSetting(nodes, expected, words) {
  const expectedText = clean(expected);
  const match = nodes.filter((node) => {
    const text = nodeText(node);
    if (exact(node, expectedText) && (BUTTON_ROLE.test(node.role) || /combobox|menuitem/i.test(node.role))) return true;
    const prefix = text.slice(0, Math.max(0, text.length - expectedText.length));
    return words.test(text) && text.endsWith(expectedText) && /[:=]\s*$/.test(prefix);
  });
  return match.length === 1 ? match[0] : null;
}

function effortDisplay(expected) {
  return {
    none: "없음",
    minimal: "최소",
    low: "낮음",
    medium: "중간",
    high: "높음",
    xhigh: "매우 높음",
    max: "최대",
  }[clean(expected).toLowerCase()] ?? clean(expected);
}

function exactEffort(nodes, expected) {
  const display = effortDisplay(expected);
  const matches = nodes.filter((node) => {
    const current = node.raw.match(/현재\s*[:=]?\s*([^,\n]+)/)?.[1];
    return BUTTON_ROLE.test(node.role) && (
      exact(node, display)
      || (/노력 변경|\b(?:effort|reasoning)\b|추론/i.test(nodeText(node)) && clean(current) === display)
    );
  });
  return matches.length === 1 ? matches[0] : null;
}

function responseContainers(nodes, content) {
  return contentNodes(nodes, content).filter((node) => RESPONSE.test(nodeText(node)) && /group|article|message|region/i.test(node.role));
}

function responseText(nodes, container) {
  return contentNodes(nodes, container)
    .filter((node) => /statictext|label|text/i.test(node.role) && !INPUT_ROLE.test(node.role))
    .map((node) => node.value || node.name)
    .filter(Boolean)
    .join("\n");
}

function isInsideCode(node) {
  for (let cursor = node; cursor; cursor = cursor.parent) {
    if (/\bcode\b|코드/i.test(nodeText(cursor))) return true;
  }
  return false;
}

function exactUserPromptInMessage(nodes, content, prompt) {
  const messages = contentNodes(nodes, content).filter((node) => /group|article|message|region/i.test(node.role)
    && /(?:^|\s)(?:user|사용자)(?:\s|$).*(?:message|메시지)|(?:message|메시지).*(?:^|\s)(?:user|사용자)(?:\s|$)/i.test(nodeText(node)));
  return messages.length === 1 && responseText(nodes, messages[0]) === prompt;
}

/**
 * Pure AX observation.  It only chooses a target when one exact titled Window
 * contains one visible Notion /chat or /ai HTML surface (or one explicitly
 * active surface).  Hidden sibling web contents are deliberately ignored.
 */
export function observeNotionAX(ax, { tabTitle, model, effort } = {}, { requireControls = true, allowDisabledSend = false } = {}) {
  const nodes = parseAX(ax);
  if (!clean(tabTitle) || !clean(model) || !clean(effort)) {
    return { status: "invalid_expectation", reason: "tabTitle, model, and effort are required" };
  }
  const windows = nodes.filter((node) => WINDOW_ROLE.test(node.role) && exact(node, clean(tabTitle)) && isVisible(node));
  if (windows.length !== 1) return { status: windows.length ? "ambiguous_target" : "target_missing", reason: "exact Window title was not unique" };

  const candidates = nodes.filter((node) => HTML_ROLE.test(node.role)
    && isDescendant(node, windows[0])
    && isVisible(node)
    && exact(node, clean(tabTitle))
    && notionChatUrl(node.url));
  if (!candidates.length) return { status: "target_missing", reason: "no visible Notion chat/ai HTML content" };
  const active = candidates.filter(isActive);
  const content = candidates.length === 1 ? candidates[0] : active.length === 1 ? active[0] : null;
  if (!content) return { status: "ambiguous_target", reason: "multiple visible Notion chat/ai contents" };

  const visible = contentNodes(nodes, content);
  if (requireControls && visible.some((node) => BUTTON_ROLE.test(node.role) && isEnabled(node) && STOP.test(nodeText(node)))) {
    return { status: "busy", reason: "an existing generation is active" };
  }
  const modelNode = exactSetting(visible, model, /\bmodel\b|모델/i);
  const effortNode = exactEffort(visible, effort);
  if (!modelNode || !effortNode) return { status: "settings_mismatch", reason: "visible model or effort did not exactly match" };
  if (!requireControls) return { status: "ready", window: windows[0], content, nodes, ax: String(ax) };

  const inputs = visible.filter((node) => INPUT_ROLE.test(node.role) && isEnabled(node));
  if (inputs.length !== 1) return { status: inputs.length ? "ambiguous_target" : "input_missing", reason: "enabled prompt input was not unique" };
  const sends = visible.filter((node) => BUTTON_ROLE.test(node.role)
    && isVisible(node)
    && (allowDisabledSend || isEnabled(node))
    && SEND.test(nodeText(node)));
  if (sends.length !== 1) return { status: sends.length ? "ambiguous_target" : "send_missing", reason: "enabled send button was not unique" };
  if (!Number.isInteger(inputs[0].index) || !Number.isInteger(sends[0].index)) return { status: "index_missing", reason: "AX did not expose a click index" };
  return { status: "ready", window: windows[0], content, input: inputs[0], send: sends[0], nodes, ax: String(ax) };
}

/** Pure visible-output extraction; it never promotes a virtualized/truncated result to complete. */
export function extractVisibleResult(ax, expected, { stable = false } = {}) {
  const snapshotTruncated = TRUNCATED.test(String(ax));
  const observation = observeNotionAX(ax, expected, { requireControls: false });
  if (observation.status !== "ready") {
    return snapshotTruncated
      ? { status: "partial", text: "", complete: false, truncated: true, stable: false, reason: "AX snapshot is virtualized or visibly truncated" }
      : observation;
  }
  const visible = contentNodes(observation.nodes, observation.content);
  const containers = responseContainers(observation.nodes, observation.content);
  if (containers.length !== 1) {
    return { status: "partial", text: "", complete: false, truncated: true, stable: false, reason: "explicit response container selection was not unique" };
  }
  const text = responseText(observation.nodes, containers[0]);
  if (!text) return { status: "no_result", reason: "visible assistant result had no text" };
  const codeVisible = contentNodes(observation.nodes, containers[0]).some((node) =>
    /group|article|region/i.test(node.role) && /\bcode\b|코드/i.test(nodeText(node)));
  const allText = visible.map(nodeText).join("\n");
  const truncated = snapshotTruncated || TRUNCATED.test(allText) || codeVisible;
  const error = ERROR.test(allText);
  const stopPresent = visible.some((node) => BUTTON_ROLE.test(node.role) && isEnabled(node) && STOP.test(nodeText(node)));
  const completionMarker = visible.some((node) => /statictext|label|text/i.test(node.role)
    && !isDescendant(node, containers[0])
    && !isInsideCode(node)
    && ["Notion AI 작업이 완료되었습니다.", "Notion AI 작업이 완료되었습니다"].includes(clean(node.value || node.name)));
  const copyEnabled = visible.some((node) => BUTTON_ROLE.test(node.role) && isEnabled(node) && COPY.test(nodeText(node)));
  const completed = !truncated && !error && !stopPresent && copyEnabled && completionMarker;
  return {
    status: truncated ? "partial" : completed ? "completed" : "incomplete",
    text,
    complete: completed,
    truncated,
    stable,
    reason: codeVisible ? "AX-only code capture cannot guarantee lossless source formatting" : truncated ? "AX is virtualized or visibly truncated" : error ? "visible error marker" : completed ? undefined : "completion evidence is incomplete",
  };
}

function promptValue(node) {
  const match = node.raw.match(/\b(?:value|text)\s*[:=]\s*["']([^"']*)["']/i);
  return match?.[1] ?? node.value ?? "";
}

function tabInventory(nodes) {
  const tabBars = nodes.filter((node) => HTML_ROLE.test(node.role) && /tab bar/i.test(nodeText(node)) && isVisible(node));
  return nodes.filter((node) => BUTTON_ROLE.test(node.role)
    && isVisible(node)
    && !TAB_ADD.test(nodeText(node))
    && tabBars.some((tabBar) => isDescendant(node, tabBar)))
    .map(nodeText).sort();
}

function hasAdditionalTab(before, after) {
  if (after.length <= before.length) return false;
  const remaining = [...after];
  for (const label of before) {
    const index = remaining.indexOf(label);
    if (index < 0) return false;
    remaining.splice(index, 1);
  }
  return remaining.length > 0;
}

function hasNewChatSurface(nodes) {
  return nodes.some((node) => isVisible(node)
    && !BUTTON_ROLE.test(node.role)
    && /^새 채팅(?: 시작)?$/.test(nodeText(node)));
}

export function createNotionDesktopAdapter(App) {
  for (const method of ["getAXState", "click", "paste", "pressKey"]) {
    if (typeof App?.[method] !== "function") throw new TypeError(`App.${method} is required`);
  }
  let sequence = 0;
  const issued = new WeakMap();
  const snapshot = async () => String(await App.getAXState(AX_OPTIONS));

  async function prepare(expectation) {
    const observation = observeNotionAX(await snapshot(), expectation, { allowDisabledSend: true });
    if (observation.status !== "ready") return observation;
    if (promptValue(observation.input) !== "") return { status: "draft_present", reason: "existing composer text must not be changed" };
    const prepared = Object.freeze({ status: "prepared", id: ++sequence, expectation: Object.freeze({ ...expectation }) });
    issued.set(prepared, "ready");
    return prepared;
  }

  async function send(prepared) {
    if (!prepared || prepared.status !== "prepared") return { status: "invalid_preparation" };
    if (issued.get(prepared) !== "ready") return { status: "invalid_preparation", reason: "prepared token is unknown or already used" };
    issued.set(prepared, "used");
    const prompt = String(prepared.expectation.prompt ?? "");
    if (!prompt) return { status: "invalid_expectation", reason: "prompt is required" };
    let observation = observeNotionAX(await snapshot(), prepared.expectation, { allowDisabledSend: true });
    if (observation.status !== "ready") return observation;
    if (promptValue(observation.input) !== "") return { status: "draft_present", reason: "existing composer text must not be changed" };
    try {
      await App.click(observation.input.index);
    } catch (error) {
      return { status: "uncertain_send", reason: "input click failed; UI state is unknown", error };
    }
    observation = observeNotionAX(await snapshot(), prepared.expectation, { allowDisabledSend: true });
    if (observation.status !== "ready") return observation;
    if (promptValue(observation.input) !== "") return { status: "draft_present", reason: "composer changed before paste" };
    try {
      await App.paste(prompt, { format: "text" });
    } catch (error) {
      return { status: "not_sent", reason: "paste failed before submit", error };
    }
    observation = observeNotionAX(await snapshot(), prepared.expectation);
    if (observation.status !== "ready") return observation;
    if (promptValue(observation.input) !== prompt) {
      return { status: "prompt_mismatch", reason: "full prompt readback did not exactly match; submit was not clicked" };
    }
    try {
      await App.click(observation.send.index);
    } catch (error) {
      return { status: "uncertain_send", reason: "submit click failed; do not retry automatically", error };
    }
    let post;
    try {
      post = observeNotionAX(await snapshot(), prepared.expectation, { requireControls: false });
    } catch (error) {
      return { status: "uncertain_send", reason: "submit click returned but post-click AX could not be read", error };
    }
    if (post.status !== "ready") return { status: "uncertain_send", reason: "submit click returned but the target could not be revalidated", observation: post };
    const postNodes = contentNodes(post.nodes, post.content);
    const stopVisible = postNodes.some((node) => BUTTON_ROLE.test(node.role) && isEnabled(node) && STOP.test(nodeText(node)));
    const postInputs = postNodes.filter((node) => INPUT_ROLE.test(node.role) && isVisible(node));
    const composerCleared = postInputs.length === 1 && promptValue(postInputs[0]) === "";
    const promptMessageVisible = exactUserPromptInMessage(post.nodes, post.content, prompt);
    if (!stopVisible && !(composerCleared && promptMessageVisible)) {
      return { status: "uncertain_send", reason: "submit click lacked an enabled stop button or a cleared composer plus exact user message" };
    }
    return { status: "sent", promptReadback: promptValue(observation.input) };
  }

  async function read(expectation) {
    const first = extractVisibleResult(await snapshot(), expectation);
    if (!["partial", "incomplete", "completed"].includes(first.status)) return first;
    const secondAx = await snapshot();
    const second = extractVisibleResult(secondAx, expectation);
    if (!["partial", "incomplete", "completed"].includes(second.status)) return second;
    // Stability is derived from two independent fresh snapshots, not cached UI state.
    return extractVisibleResult(secondAx, expectation, { stable: second.text === first.text });
  }

  async function createDistinctTab() {
    const first = parseAX(await snapshot());
    const tabBars = first.filter((node) => HTML_ROLE.test(node.role) && /tab bar/i.test(nodeText(node)) && isVisible(node));
    const buttons = first.filter((node) => {
      return BUTTON_ROLE.test(node.role)
        && isEnabled(node)
        && TAB_ADD.test(nodeText(node))
        && tabBars.some((tabBar) => isDescendant(node, tabBar));
    });
    if (buttons.length !== 1 || !Number.isInteger(buttons[0]?.index)) return { status: buttons.length ? "ambiguous_target" : "target_missing", reason: "top Tab Bar add button was not unique" };
    try {
      await App.click(buttons[0].index);
    } catch (error) {
      return { status: "uncertain_ui", reason: "tab creation click failed", error };
    }
    const fresh = parseAX(await snapshot());
    const tabChanged = hasAdditionalTab(tabInventory(first), tabInventory(fresh));
    if (!tabChanged) return { status: "unverified", reason: "no additional top-bar tab was observed" };
    const starters = fresh.filter((node) => BUTTON_ROLE.test(node.role) && isEnabled(node) && NEW_CHAT.test(nodeText(node)));
    if (!starters.length) return { status: "unverified", reason: tabChanged ? "tab inventory changed but no fresh new-chat surface was available" : "tab creation click had no fresh inventory or new-chat evidence" };
    if (starters.length !== 1 || !Number.isInteger(starters[0].index)) return { status: "ambiguous_target", reason: "fresh 새 채팅 시작 button was not unique" };
    try {
      await App.click(starters[0].index);
    } catch (error) {
      return { status: "uncertain_ui", reason: "새 채팅 시작 click failed", error };
    }
    const afterStart = parseAX(await snapshot());
    if (!tabChanged || !hasNewChatSurface(afterStart)) {
      return { status: "unverified", reason: "새 채팅 시작 click lacked a fresh changed tab inventory and new-chat surface" };
    }
    return { status: "new_chat_started" };
  }

  return Object.freeze({ prepare, send, read, createDistinctTab });
}
