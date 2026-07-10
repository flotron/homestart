const LEGACY_SESSIONS_KEY = "homestart.codex.sessions";
const LEGACY_MESSAGES_KEY = "homestart.codex.messages";
const MIGRATION_KEY = "homestart.codex.serverMigration";
const DEFAULT_PERMISSIONS = {
  sandbox: "read-only",
  approval: "never",
  model: "",
};

const historyNode = document.querySelector("#codex-history");
const messagesNode = document.querySelector("#codex-messages");
const form = document.querySelector("#codex-form");
const input = document.querySelector("#codex-message");
const send = document.querySelector("#codex-send");
const create = document.querySelector("#codex-new");
const remove = document.querySelector("#codex-delete");
const sandbox = document.querySelector("#codex-sandbox");
const approval = document.querySelector("#codex-approval");
const model = document.querySelector("#codex-model");
const fileInput = document.querySelector("#codex-files");
const attachmentList = document.querySelector("#codex-attachment-list");
const importOpen = document.querySelector("#codex-import-open");
const importDialog = document.querySelector("#codex-import-dialog");
const importForm = document.querySelector("#codex-import-form");
const importText = document.querySelector("#codex-import-text");
const importCancel = document.querySelector("#codex-import-cancel");

let chats = [];
let activeId = "";
let activeMessages = [];
let pendingAttachments = [];

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const result = await response.json();
  if (!response.ok || result.ok === false) {
    throw new Error(result.error || "Request failed");
  }
  return result;
}

function legacySessions() {
  try {
    const sessions = JSON.parse(localStorage.getItem(LEGACY_SESSIONS_KEY) || "[]");
    if (Array.isArray(sessions) && sessions.length) return sessions;
  } catch {
    // Fall through to legacy single-message storage.
  }

  try {
    const messages = JSON.parse(localStorage.getItem(LEGACY_MESSAGES_KEY) || "[]");
    if (Array.isArray(messages) && messages.length) {
      return [{ messages, permissions: DEFAULT_PERMISSIONS }];
    }
  } catch {
    // No legacy data.
  }

  return [];
}

async function migrateLegacyChats() {
  if (localStorage.getItem(MIGRATION_KEY)) return;
  const legacy = legacySessions();
  for (const session of legacy) {
    await requestJson("/api/codex/chats", {
      method: "POST",
      body: JSON.stringify({
        messages: session.messages || [],
        permissions: session.permissions || DEFAULT_PERMISSIONS,
      }),
    });
  }
  localStorage.setItem(MIGRATION_KEY, String(Date.now()));
}

async function loadChats(preferredId = activeId) {
  const data = await requestJson("/api/codex/chats");
  chats = data.chats || [];
  if (!chats.length) {
    const created = await createChat(false);
    chats = [created.chat];
  }
  activeId = chats.some((chat) => chat.id === preferredId) ? preferredId : chats[0].id;
  renderHistory();
  await loadChat(activeId);
}

async function createChat(render = true) {
  const data = await requestJson("/api/codex/chats", {
    method: "POST",
    body: JSON.stringify({ permissions: currentPermissions() }),
  });
  if (render) await loadChats(data.chat.id);
  return data;
}

async function loadChat(id) {
  const data = await requestJson(`/api/codex/chat?id=${encodeURIComponent(id)}`);
  const chat = data.chat;
  activeId = chat.id;
  activeMessages = data.messages || [];
  const index = chats.findIndex((item) => item.id === chat.id);
  if (index >= 0) chats[index] = chat;
  renderHistory();
  renderPermissions(chat.permissions);
  renderMessages();
}

function activeChat() {
  return chats.find((chat) => chat.id === activeId);
}

function currentPermissions() {
  return {
    sandbox: sandbox.value || DEFAULT_PERMISSIONS.sandbox,
    approval: approval.value || DEFAULT_PERMISSIONS.approval,
    model: model.value || DEFAULT_PERMISSIONS.model,
  };
}

function attachmentLabel(item) {
  return `${item.name} · ${item.kind === "image" ? "image" : "text"}`;
}

function renderPendingAttachments() {
  attachmentList.replaceChildren();
  pendingAttachments.forEach((item, index) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "codex-attachment-chip";
    chip.textContent = attachmentLabel(item);
    chip.title = "Remove attachment";
    chip.addEventListener("click", () => {
      pendingAttachments.splice(index, 1);
      renderPendingAttachments();
    });
    attachmentList.appendChild(chip);
  });
}

function fileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(reader.result));
    reader.addEventListener("error", reject);
    reader.readAsDataURL(file);
  });
}

function fileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(reader.result));
    reader.addEventListener("error", reject);
    reader.readAsText(file);
  });
}

async function addFiles(files) {
  for (const file of [...files].slice(0, 6 - pendingAttachments.length)) {
    if (file.size > 1_500_000) {
      showError(new Error(`${file.name} is too large. Limit is 1.5 MB.`));
      continue;
    }
    if (file.type.startsWith("image/")) {
      pendingAttachments.push({
        name: file.name,
        mime: file.type,
        kind: "image",
        content: await fileAsDataUrl(file),
      });
      continue;
    }
    pendingAttachments.push({
      name: file.name,
      mime: file.type || "text/plain",
      kind: "text",
      content: String(await fileAsText(file)).slice(0, 200000),
    });
  }
  fileInput.value = "";
  renderPendingAttachments();
}

function renderHistory() {
  historyNode.replaceChildren();
  chats.forEach((chat) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `codex-history-item ${chat.id === activeId ? "active" : ""}`;
    const title = document.createElement("strong");
    title.textContent = chat.title || "New chat";
    const meta = document.createElement("span");
    meta.textContent = `${chat.messageCount || 0} messages · ${new Date(chat.updatedAt || Date.now()).toLocaleString()}`;
    button.append(title, meta);
    button.addEventListener("click", () => loadChat(chat.id).catch(showError));
    historyNode.appendChild(button);
  });
}

function renderPermissions(permissions = DEFAULT_PERMISSIONS) {
  sandbox.value = permissions.sandbox || DEFAULT_PERMISSIONS.sandbox;
  approval.value = permissions.approval || DEFAULT_PERMISSIONS.approval;
  model.value = permissions.model || DEFAULT_PERMISSIONS.model;
}

function renderMessages() {
  messagesNode.replaceChildren();
  if (!activeMessages.length) {
    const empty = document.createElement("div");
    empty.className = "codex-empty";
    empty.textContent = "No messages yet.";
    messagesNode.appendChild(empty);
    return;
  }

  activeMessages.forEach((message) => {
    const bubble = document.createElement("article");
    bubble.className = `codex-bubble ${message.role}`;
    const role = document.createElement("span");
    role.textContent = message.role === "user" ? "You" : "Codex";
    const content = document.createElement("p");
    content.textContent = message.content;
    bubble.append(role, content);
    if (message.attachments?.length) {
      const attachments = document.createElement("div");
      attachments.className = "codex-message-attachments";
      message.attachments.forEach((item) => {
        const attachment = document.createElement("span");
        attachment.textContent = attachmentLabel(item);
        attachments.appendChild(attachment);
      });
      bubble.appendChild(attachments);
    }
    messagesNode.appendChild(bubble);
  });
  messagesNode.scrollTop = messagesNode.scrollHeight;
}

function showError(error) {
  activeMessages.push({ role: "assistant", content: error.message });
  renderMessages();
}

function setBusy(isBusy) {
  send.disabled = isBusy;
  create.disabled = isBusy;
  remove.disabled = isBusy;
  input.disabled = isBusy;
  sandbox.disabled = isBusy;
  approval.disabled = isBusy;
  model.disabled = isBusy;
  send.textContent = isBusy ? "Sending..." : "Send";
}

async function updatePermissions() {
  if (!activeId) return;
  const data = await requestJson("/api/codex/chat/update", {
    method: "POST",
    body: JSON.stringify({
      chat_id: activeId,
      permissions: currentPermissions(),
    }),
  });
  const index = chats.findIndex((chat) => chat.id === activeId);
  if (index >= 0) chats[index] = data.chat;
  renderHistory();
}

async function sendMessage(event) {
  event.preventDefault();
  const content = input.value.trim();
  if ((!content && !pendingAttachments.length) || !activeId) return;
  if (sandbox.value === "danger-full-access") {
    const confirmed = window.confirm("Full access can modify this machine. Continue with this permission level?");
    if (!confirmed) return;
  }

  const attachments = [...pendingAttachments];
  activeMessages.push({ role: "user", content, attachments });
  input.value = "";
  pendingAttachments = [];
  renderPendingAttachments();
  renderMessages();
  setBusy(true);

  try {
    const data = await requestJson("/api/codex/chat", {
      method: "POST",
      body: JSON.stringify({
        chat_id: activeId,
        content,
        attachments,
        permissions: currentPermissions(),
      }),
    });
    activeMessages = data.messages || [];
    const index = chats.findIndex((chat) => chat.id === data.chat.id);
    if (index >= 0) chats[index] = data.chat;
    chats.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    activeId = data.chat.id;
    renderHistory();
    renderPermissions(data.chat.permissions);
    renderMessages();
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
    input.focus();
  }
}

async function deleteChat() {
  const chat = activeChat();
  if (!chat) return;
  const confirmed = window.confirm(`Delete "${chat.title || "New chat"}"?`);
  if (!confirmed) return;
  await requestJson("/api/codex/chat/delete", {
    method: "POST",
    body: JSON.stringify({ chat_id: chat.id }),
  });
  await loadChats(chats.find((item) => item.id !== chat.id)?.id || "");
}

async function importChat(event) {
  event.preventDefault();
  const content = importText.value.trim();
  if (!content) return;
  const data = await requestJson("/api/codex/chats", {
    method: "POST",
    body: JSON.stringify({
      messages: [
        {
          role: "user",
          content: `Imported chat history:\n\n${content}`,
          attachments: [],
        },
      ],
      permissions: currentPermissions(),
    }),
  });
  importText.value = "";
  importDialog.close();
  await loadChats(data.chat.id);
}

form.addEventListener("submit", sendMessage);
create.addEventListener("click", () => createChat().then(() => input.focus()).catch(showError));
remove.addEventListener("click", () => deleteChat().catch(showError));
fileInput.addEventListener("change", () => addFiles(fileInput.files).catch(showError));
importOpen.addEventListener("click", () => importDialog.showModal());
importCancel.addEventListener("click", () => importDialog.close());
importForm.addEventListener("submit", (event) => importChat(event).catch(showError));
sandbox.addEventListener("change", () => updatePermissions().catch(showError));
approval.addEventListener("change", () => updatePermissions().catch(showError));
model.addEventListener("change", () => updatePermissions().catch(showError));
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

migrateLegacyChats()
  .then(() => loadChats())
  .catch(showError);
