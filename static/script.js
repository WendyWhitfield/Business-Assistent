// === STATE ===
let currentSection = "business-strategie";
let isRecording = false;
let recognition = null;

// === INIT ===
document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initInput();
    initVoice();
    initHub();
    initMobileMenu();
    switchSection("home", "Hallo Wendy");
});

// === NAVIGATION ===
function initNavigation() {
    document.querySelectorAll(".nav-item").forEach(item => {
        item.addEventListener("click", () => {
            const section = item.dataset.section;
            const label = item.textContent.trim();
            switchSection(section, label);
        });
    });

    document.querySelectorAll(".nav-section-title").forEach(title => {
        title.addEventListener("click", () => {
            title.closest(".nav-section").classList.toggle("collapsed");
        });
    });
}

async function switchSection(section, label) {
    currentSection = section;
    document.getElementById("sectionLabel").textContent = label;

    document.querySelectorAll(".nav-item").forEach(i => i.classList.remove("active"));
    document.querySelector(`[data-section="${section}"]`)?.classList.add("active");

    // Chat leeren und Typing-Indicator zeigen
    const messages = document.getElementById("chatMessages");
    messages.innerHTML = "";
    const typing = appendTyping();

    // Personalisierte Begrüßung vom Server holen
    try {
        const res = await fetch("/api/section-start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ section })
        });
        const data = await res.json();
        typing.remove();
        appendMessage("assistant", data.message, false);
    } catch {
        typing.remove();
        appendMessage("assistant", `${label} — bereit.`, false);
    }
}

// === CHAT ===
function initInput() {
    const input = document.getElementById("chatInput");
    const sendBtn = document.getElementById("sendBtn");

    input.addEventListener("input", () => {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 120) + "px";
    });

    input.addEventListener("keydown", e => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener("click", sendMessage);
}

async function sendMessage() {
    const input = document.getElementById("chatInput");
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    input.style.height = "auto";

    appendMessage("user", text);
    const typing = appendTyping();

    try {
        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ section: currentSection, message: text })
        });
        const data = await res.json();
        typing.remove();
        appendMessage("assistant", data.response);

        // Kurze Animation wenn etwas automatisch gespeichert wurde
        if (data.auto_saved) {
            showSaveIndicator();
        }
    } catch (err) {
        typing.remove();
        appendMessage("assistant", "Verbindungsfehler — bitte nochmal versuchen.");
    }
}

function showSaveIndicator() {
    const indicator = document.createElement("div");
    indicator.className = "save-indicator";
    indicator.textContent = "✓ Im Hub gespeichert";
    document.getElementById("chatMessages").appendChild(indicator);
    setTimeout(() => indicator.remove(), 3000);
}

function appendMessage(role, content, showTime = true) {
    const messages = document.getElementById("chatMessages");

    const div = document.createElement("div");
    div.className = `message ${role}`;

    const now = new Date();
    const time = now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });

    div.innerHTML = `
        <div class="message-bubble">${escapeHtml(content)}</div>
        ${showTime ? `<div class="message-time">${time}</div>` : ""}
    `;

    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
}

function appendTyping() {
    const messages = document.getElementById("chatMessages");
    const div = document.createElement("div");
    div.className = "message assistant typing";
    div.innerHTML = `
        <div class="message-bubble">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
        </div>
    `;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
}

function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\n/g, "<br>");
}

// === VOICE ===
function initVoice() {
    const micBtn = document.getElementById("micBtn");

    if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
        micBtn.style.display = "none";
        return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.lang = "de-DE";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        const input = document.getElementById("chatInput");
        input.value = (input.value + " " + transcript).trim();
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 120) + "px";
    };

    recognition.onend = () => {
        isRecording = false;
        micBtn.classList.remove("recording");
    };

    micBtn.addEventListener("click", () => {
        if (isRecording) {
            recognition.stop();
        } else {
            recognition.start();
            isRecording = true;
            micBtn.classList.add("recording");
        }
    });
}

// === HUB ===
function initHub() {
    const hubToggle = document.getElementById("hubToggle");
    const hubPanel = document.getElementById("hubPanel");
    const hubClose = document.getElementById("hubClose");

    hubToggle.addEventListener("click", async () => {
        hubPanel.classList.toggle("open");
        if (hubPanel.classList.contains("open")) {
            await loadHub();
        }
    });

    hubClose.addEventListener("click", () => {
        hubPanel.classList.remove("open");
    });
}

async function loadHub() {
    const hubContent = document.getElementById("hubContent");
    try {
        const res = await fetch("/api/hub");
        const data = await res.json();
        hubContent.textContent = data.content;
    } catch {
        hubContent.textContent = "Hub konnte nicht geladen werden.";
    }
}

// === MOBILE MENU ===
function initMobileMenu() {
    const hamburger = document.getElementById("hamburgerBtn");
    const sidebar = document.querySelector(".sidebar");
    const overlay = document.getElementById("mobileOverlay");

    function openSidebar() {
        sidebar.classList.add("mobile-open");
        overlay.classList.add("active");
    }

    function closeSidebar() {
        sidebar.classList.remove("mobile-open");
        overlay.classList.remove("active");
    }

    hamburger.addEventListener("click", openSidebar);
    overlay.addEventListener("click", closeSidebar);

    document.querySelectorAll(".nav-item").forEach(item => {
        item.addEventListener("click", closeSidebar);
    });
}
