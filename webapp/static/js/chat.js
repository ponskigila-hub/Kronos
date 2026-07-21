(function () {
  const log = document.getElementById("chatLog");
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const chips = document.querySelectorAll(".suggestion-chip");

  function addMessage(role, text, imageUrl) {
    const wrap = document.createElement("div");
    wrap.className = "msg " + (role === "user" ? "msg-user" : "msg-bot");
    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.textContent = text;
    wrap.appendChild(bubble);
    if (imageUrl) {
      const img = document.createElement("img");
      img.src = imageUrl;
      img.alt = "chart";
      wrap.appendChild(img);
    }
    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
    return wrap;
  }

  async function send(text) {
    if (!text.trim()) return;
    addMessage("user", text);
    const thinking = addMessage("bot", "…thinking");

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await resp.json();
      thinking.remove();
      addMessage("bot", data.text || "(no response)", data.image_url);
    } catch (err) {
      thinking.remove();
      addMessage("bot", "Connection error — is the server still running?");
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = "";
    send(text);
  });

  chips.forEach((chip) => {
    chip.addEventListener("click", () => send(chip.textContent));
  });

  // support ?prefill=... from dashboard/watchlist links
  const params = new URLSearchParams(window.location.search);
  const prefill = params.get("prefill");
  if (prefill) {
    input.value = prefill.replace(/\+/g, " ");
  }
})();
