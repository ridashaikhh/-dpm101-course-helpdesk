(() => {
  const $ = (id) => document.getElementById(id);
  const chat = $("chat"), form = $("form"), input = $("input"), send = $("send");
  const EXAMPLES = [
    "What is the minimum score needed to pass the course?",
    "When is the Capstone Product Case due?",
    "Is the final exam open-book or closed-book?",
    "Can I take the exam on my iPad?",
    "How much does the Verified Certificate cost?",
    "How many weekly quizzes are there?",
  ];
  let conversationId = null;
  let busy = false;

  const newId = () =>
    (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2)).replace(/[^A-Za-z0-9_-]/g, "");

  function setBusy(v) {
    busy = v;
    send.disabled = v;
    input.disabled = v;
    document.querySelectorAll("#examples button").forEach((b) => (b.disabled = v));
    if (!v) input.focus();
  }

  function addMessage(role, text, extraClass = "") {
    const wrap = document.createElement("div");
    wrap.className = `msg ${role} ${extraClass}`.trim();
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;           // textContent: never interpret model output as HTML
    wrap.appendChild(bubble);
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return { wrap, bubble };
  }

  function addMeta(bubble, data) {
    const meta = document.createElement("div");
    meta.className = "meta";
    const chip = (text, cls = "") => {
      const c = document.createElement("span");
      c.className = `chip ${cls}`.trim();
      c.textContent = text;
      meta.appendChild(c);
    };
    if (data.sources && data.sources.length) data.sources.forEach((s) => chip(`📄 ${s.file}`));
    else if (!data.covered) chip("No matching course document", "warn");
    if (data.served_from === "cache") chip("⚡ From cache", "cache");
    else if (data.served_from === "coalesced") chip("⚡ Shared an in-flight answer", "cache");
    else chip("Answered by Gemini");
    bubble.appendChild(meta);
  }

  function renderStats(s) {
    if (!s) return;
    $("cTotal").textContent = s.total_questions ?? 0;
    $("cApi").textContent = s.api_calls ?? 0;
    $("cCache").textContent = s.cache_hits ?? 0;
  }

  async function refreshStats() {
    try {
      const r = await fetch("/api/stats");
      if (r.ok) renderStats(await r.json());
    } catch (_) { /* counters are best-effort */ }
  }

  async function ask(question) {
    if (busy) return;                      // blocks double-clicks / double-Enter
    question = question.trim();
    if (!question) return;
    setBusy(true);
    addMessage("user", question);
    input.value = "";
    input.style.height = "auto";
    const pending = addMessage("bot", "");
    pending.bubble.innerHTML = '<span class="typing" aria-label="Thinking"><i></i><i></i><i></i></span>';

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 60000);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, conversation_id: conversationId, request_id: newId() }),
        signal: ctrl.signal,
      });
      let data = null;
      try { data = await res.json(); } catch (_) {}
      if (!res.ok || !data || data.status !== "ok") {
        pending.wrap.classList.add("error");
        pending.bubble.textContent = (data && data.message) || "Something went wrong. Please try again.";
        renderStats(data && data.stats);
      } else {
        conversationId = data.conversation_id;
        pending.bubble.textContent = data.answer;
        addMeta(pending.bubble, data);
        renderStats(data.stats);
      }
    } catch (err) {
      pending.wrap.classList.add("error");
      pending.bubble.textContent = err.name === "AbortError"
        ? "The request took too long. Please try again."
        : "Could not reach the server. Check your connection and try again.";
    } finally {
      clearTimeout(timer);
      setBusy(false);
      chat.scrollTop = chat.scrollHeight;
    }
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input.value); }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  });
  $("newChat").addEventListener("click", () => {
    if (busy) return;
    conversationId = null;
    chat.innerHTML = "";
    addMessage("bot", "New conversation started. What would you like to know about DPM-101?");
  });

  EXAMPLES.forEach((q) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = q;
    b.addEventListener("click", () => ask(q));
    $("examples").appendChild(b);
  });

  refreshStats();
  setInterval(refreshStats, 8000);
})();
