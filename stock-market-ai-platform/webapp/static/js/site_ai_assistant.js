(() => {
  "use strict";
  if (document.getElementById("ds-ai-launcher")) return;

  const state = { history: [], busy: false };
  const root = document.createElement("div");
  root.id = "ds-ai-root";
  root.innerHTML = `
    <button id="ds-ai-launcher" type="button" aria-label="Open Shepherd AI" aria-expanded="false">
      <span class="ds-ai-spark">✦</span><span>Ask Shepherd AI</span>
    </button>
    <section id="ds-ai-panel" role="dialog" aria-modal="false" aria-labelledby="ds-ai-title" hidden>
      <header class="ds-ai-header">
        <div><strong id="ds-ai-title">Shepherd AI</strong><small>Page-aware site guide</small></div>
        <button id="ds-ai-close" type="button" aria-label="Close assistant">×</button>
      </header>
      <div id="ds-ai-messages" class="ds-ai-messages" aria-live="polite">
        <div class="ds-ai-message ds-ai-assistant">Hi! Ask me how this page works, what the numbers mean, or how Data Shepherd handles its research and holdouts.</div>
      </div>
      <div class="ds-ai-suggestions">
        <button type="button">Explain this page</button>
        <button type="button">What does this data mean?</button>
        <button type="button">How are holdouts protected?</button>
      </div>
      <form id="ds-ai-form">
        <label class="ds-ai-sr-only" for="ds-ai-input">Ask a question</label>
        <textarea id="ds-ai-input" maxlength="2000" rows="2" placeholder="Ask about this page…" required></textarea>
        <button id="ds-ai-send" type="submit">Send</button>
      </form>
      <p class="ds-ai-disclaimer">Research and educational information only—not financial advice.</p>
    </section>`;
  document.body.appendChild(root);

  const launcher = root.querySelector("#ds-ai-launcher");
  const panel = root.querySelector("#ds-ai-panel");
  const close = root.querySelector("#ds-ai-close");
  const form = root.querySelector("#ds-ai-form");
  const input = root.querySelector("#ds-ai-input");
  const send = root.querySelector("#ds-ai-send");
  const messages = root.querySelector("#ds-ai-messages");

  function setOpen(open) {
    panel.hidden = !open;
    launcher.setAttribute("aria-expanded", String(open));
    if (open) setTimeout(() => input.focus(), 0);
  }

  function addMessage(role, content) {
    const node = document.createElement("div");
    node.className = `ds-ai-message ds-ai-${role}`;
    node.textContent = content;
    messages.appendChild(node);
    messages.scrollTop = messages.scrollHeight;
    return node;
  }

  function pageContext() {
    const sensitivePath = ["/verify-email/", "/complete-account", "/change-password", "/signup"].some(
      (prefix) => location.pathname.startsWith(prefix)
    );
    if (sensitivePath) {
      return { title: "Data Shepherd account page", path: "/account", visible_text: "" };
    }
    const clone = document.body.cloneNode(true);
    clone.querySelector("#ds-ai-root")?.remove();
    clone.querySelectorAll("script,style,noscript,input,textarea,select").forEach((node) => node.remove());
    return {
      title: document.title,
      path: location.pathname + location.search,
      visible_text: (clone.innerText || "").replace(/\s+/g, " ").trim().slice(0, 12000)
    };
  }

  async function ask(question) {
    if (state.busy) return;
    state.busy = true;
    send.disabled = true;
    input.disabled = true;
    addMessage("user", question);
    const pending = addMessage("assistant", "Thinking…");
    try {
      const response = await fetch("/api/site-assistant", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, page: pageContext(), history: state.history.slice(-8) })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "The assistant is unavailable.");
      pending.textContent = data.answer;
      state.history.push({ role: "user", content: question }, { role: "assistant", content: data.answer });
      state.history = state.history.slice(-8);
    } catch (error) {
      pending.textContent = error.message || "The assistant is temporarily unavailable.";
      pending.classList.add("ds-ai-error");
    } finally {
      state.busy = false;
      send.disabled = false;
      input.disabled = false;
      input.focus();
    }
  }

  launcher.addEventListener("click", () => setOpen(panel.hidden));
  close.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !panel.hidden) setOpen(false); });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    input.value = "";
    ask(question);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  root.querySelectorAll(".ds-ai-suggestions button").forEach((button) => {
    button.addEventListener("click", () => ask(button.textContent.trim()));
  });
})();
