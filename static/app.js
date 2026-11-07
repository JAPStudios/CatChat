(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let token = "";
  let currentUser = null;
  let activeConversation = null;
  let lastMessageId = 0;
  let pollTimer = null;
  let polling = false;
  let authMode = "login";

  class ApiError extends Error {
    constructor(message, status, data) {
      super(message);
      this.status = status;
      this.data = data;
    }
  }

  function setStatus(message, isError) {
    const node = $("statusMessage");
    node.textContent = message || "";
    node.classList.toggle("error", Boolean(isError));
  }

  async function api(path, options) {
    const opts = options || {};
    const headers = new Headers(opts.headers || {});
    if (token) headers.set("Authorization", "Bearer " + token);
    if (opts.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(path, Object.assign({}, opts, { headers }));
    let data = {};
    try { data = await response.json(); } catch (_error) { data = {}; }
    if (!response.ok) {
      const message = data.detail || data.error || ("Request failed (" + response.status + ")");
      throw new ApiError(String(message), response.status, data);
    }
    return data;
  }

  function showAuthenticated(user) {
    currentUser = user;
    $("authView").hidden = true;
    $("chatView").hidden = false;
    $("accountBar").hidden = false;
    $("accountName").textContent = user.display_name || user.username;
    loadConversations();
  }

  function showAuth() {
    token = "";
    currentUser = null;
    activeConversation = null;
    stopPolling();
    $("chatView").hidden = true;
    $("accountBar").hidden = true;
    $("authView").hidden = false;
    $("conversationList").replaceChildren();
    $("messages").replaceChildren();
  }

  function stopPolling() {
    if (pollTimer !== null) window.clearTimeout(pollTimer);
    pollTimer = null;
    polling = false;
  }

  function setAuthMode(mode) {
    authMode = mode;
    const registering = mode === "register";
    $("loginForm").hidden = registering;
    $("registerForm").hidden = !registering;
    $("authTitle").textContent = registering ? "Create a CatChat account" : "Sign in to CatChat";
    $("toggleAuthButton").textContent = registering ? "Already have an account? Sign in" : "Create a CatChat account";
    setStatus("");
  }

  async function login(username, password) {
    const data = await api("/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ username, password })
    });
    token = data.token;
    showAuthenticated(data.user);
    setStatus("Signed in.");
  }

  async function register(username, displayName, password) {
    await api("/v1/accounts", {
      method: "POST",
      body: JSON.stringify({ username, display_name: displayName || username, password })
    });
    await login(username, password);
  }

  function conversationLabel(conversation) {
    if (conversation.kind === "group") return conversation.name || "Group conversation";
    return conversation.peer_display_name || conversation.peer_username || "Direct conversation";
  }

  function renderConversations(conversations) {
    const list = $("conversationList");
    list.replaceChildren();
    $("emptyConversations").hidden = conversations.length > 0;
    conversations.forEach((conversation) => {
      const item = document.createElement("li");
      item.className = "conversation-item";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "conversation-button" + (activeConversation === conversation.id ? " active" : "");
      const copy = document.createElement("span");
      copy.className = "conversation-copy";
      const name = document.createElement("span");
      name.className = "conversation-name";
      name.textContent = conversationLabel(conversation);
      const preview = document.createElement("span");
      preview.className = "conversation-preview";
      preview.textContent = conversation.last_message || (conversation.kind === "group" ? "Group conversation" : "No messages yet");
      copy.append(name, preview);
      button.append(copy);
      if (conversation.unread_count > 0) {
        const unread = document.createElement("span");
        unread.className = "unread-count";
        unread.textContent = String(conversation.unread_count);
        button.append(unread);
      }
      button.addEventListener("click", () => openConversation(conversation));
      item.append(button);
      list.append(item);
    });
  }

  async function loadConversations() {
    try {
      const data = await api("/v1/conversations");
      renderConversations(data.conversations || []);
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  function appendMessage(message) {
    if (!message || typeof message.id !== "number" || message.id <= lastMessageId) return;
    const list = $("messages");
    const item = document.createElement("li");
    item.className = "message";
    if (message.sender === (currentUser && currentUser.username)) item.classList.add("mine");
    if (message.is_agent) item.classList.add("agent");
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const timeText = message.created_at ? new Date(message.created_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
    meta.textContent = (message.display_name || message.sender || "Unknown") + (timeText ? " · " + timeText : "");
    const body = document.createElement("p");
    body.className = "message-body";
    body.textContent = message.content || "";
    item.append(meta, body);
    list.append(item);
    lastMessageId = message.id;
    list.scrollTop = list.scrollHeight;
  }

  async function loadMessages(afterId) {
    if (!activeConversation) return;
    const data = await api(
      "/v1/conversations/" + encodeURIComponent(activeConversation) + "/messages?after_id=" + String(afterId) + "&limit=100"
    );
    (data.messages || []).forEach(appendMessage);
    if (lastMessageId > 0) {
      await api("/v1/conversations/" + encodeURIComponent(activeConversation) + "/read", {
        method: "POST",
        body: JSON.stringify({ message_id: lastMessageId })
      });
    }
  }

  async function openConversation(conversation) {
    activeConversation = conversation.id;
    lastMessageId = 0;
    stopPolling();
    $("emptyState").hidden = true;
    $("conversationView").hidden = false;
    $("conversationTitle").textContent = conversationLabel(conversation);
    $("conversationKind").textContent = conversation.kind === "group" ? "Group conversation" : "Direct message";
    $("messages").replaceChildren();
    try {
      await loadMessages(0);
      await loadConversations();
      pollMessages();
      $("messageInput").focus();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function pollMessages() {
    if (!activeConversation || polling) return;
    polling = true;
    try {
      await loadMessages(lastMessageId);
      await loadConversations();
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      polling = false;
      if (activeConversation) pollTimer = window.setTimeout(pollMessages, 2200);
    }
  }

  async function sendMessage(content) {
    if (!activeConversation) return;
    $("sendButton").disabled = true;
    try {
      const data = await api("/v1/conversations/" + encodeURIComponent(activeConversation) + "/messages", {
        method: "POST",
        body: JSON.stringify({ content })
      });
      (data.messages || []).forEach(appendMessage);
      $("messageInput").value = "";
      await loadConversations();
      $("messageInput").focus();
    } catch (error) {
      if (error.status === 502 && error.data && error.data.message_id) {
        await loadMessages(lastMessageId);
        setStatus("The message was saved. The assistant could not reply: " + error.message, true);
      } else {
        setStatus(error.message, true);
      }
    } finally {
      $("sendButton").disabled = false;
    }
  }

  async function createDirect(username) {
    const data = await api("/v1/conversations/direct", {
      method: "POST",
      body: JSON.stringify({ recipient_username: username })
    });
    $("directDialog").close();
    await loadConversations();
    await openConversation({ id: data.conversation_id, kind: "direct", peer_username: username });
  }

  async function createGroup(name, participants) {
    const data = await api("/v1/conversations/group", {
      method: "POST",
      body: JSON.stringify({ name, participants })
    });
    $("groupDialog").close();
    await loadConversations();
    await openConversation({ id: data.conversation_id, kind: "group", name });
  }

  $("toggleAuthButton").addEventListener("click", () => {
    setAuthMode(authMode === "login" ? "register" : "login");
  });

  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await login(String(form.get("username") || "").trim(), String(form.get("password") || ""));
    } catch (error) {
      setStatus(error.message, true);
    }
  });

  $("registerForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await register(
        String(form.get("username") || "").trim(),
        String(form.get("display_name") || "").trim(),
        String(form.get("password") || "")
      );
    } catch (error) {
      setStatus(error.message, true);
    }
  });

  $("logoutButton").addEventListener("click", async () => {
    try { await api("/v1/sessions", { method: "DELETE" }); } catch (_error) { /* local logout still proceeds */ }
    showAuth();
    setStatus("Signed out.");
  });

  $("newDirectButton").addEventListener("click", () => $("directDialog").showModal());
  $("newGroupButton").addEventListener("click", () => $("groupDialog").showModal());
  $("refreshButton").addEventListener("click", () => {
    loadMessages(lastMessageId).then(loadConversations).catch((error) => setStatus(error.message, true));
  });

  $("directForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = $("recipientUsername").value.trim();
    try { await createDirect(username); } catch (error) { setStatus(error.message, true); }
  });

  $("groupForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = $("groupName").value.trim();
    const participants = $("groupParticipants").value.split(",").map((item) => item.trim()).filter(Boolean);
    try { await createGroup(name, participants); } catch (error) { setStatus(error.message, true); }
  });

  document.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", () => $(button.dataset.close).close());
  });

  $("messageForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const content = $("messageInput").value.trim();
    if (content) sendMessage(content);
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
})();
