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
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 60000); // 60s Timeout

        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ section: currentSection, message: text }),
            signal: controller.signal
        });
        clearTimeout(timeout);

        if (!res.ok) throw new Error("Server Fehler: " + res.status);
        const data = await res.json();
        typing.remove();
        appendMessage("assistant", data.response);

        if (data.auto_saved) {
            showSaveIndicator();
        }
    } catch (err) {
        typing.remove();
        if (err.name === "AbortError") {
            appendMessage("assistant", "Antwort hat zu lange gedauert — bitte nochmal versuchen.");
        } else {
            appendMessage("assistant", "Verbindungsfehler — bitte prüfe deine Internetverbindung.");
        }
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

// === VOICE (WhatsApp-Style) ===
function initVoice() {
    const micBtn = document.getElementById("micBtn");

    if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
        micBtn.style.display = "none";
        return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.lang = "de-DE";
    recognition.continuous = true;
    recognition.interimResults = false;

    let recordingMode = "idle"; // idle, holding, locked
    let touchStartY = 0;
    let fullTranscript = "";
    let intentionalStop = false;
    let timerInterval = null;
    let timerSeconds = 0;

    // --- Timer ---
    function startTimer() {
        timerSeconds = 0;
        updateTimer();
        timerInterval = setInterval(() => {
            timerSeconds++;
            updateTimer();
        }, 1000);
    }

    function stopTimer() {
        clearInterval(timerInterval);
        timerInterval = null;
        const el = document.getElementById("recordingTimer");
        if (el) el.remove();
    }

    function updateTimer() {
        let el = document.getElementById("recordingTimer");
        if (!el) {
            el = document.createElement("div");
            el.id = "recordingTimer";
            el.className = "recording-timer";
            micBtn.parentNode.insertBefore(el, micBtn);
        }
        const m = String(Math.floor(timerSeconds / 60)).padStart(2, "0");
        const s = String(timerSeconds % 60).padStart(2, "0");
        el.textContent = m + ":" + s;
    }

    // --- Hint ---
    function showHint(locked) {
        let hint = document.getElementById("recordingHint");
        if (!hint) {
            hint = document.createElement("div");
            hint.id = "recordingHint";
            document.querySelector(".chat-input-area").prepend(hint);
        }
        hint.className = "recording-hint" + (locked ? " locked" : "");
        hint.textContent = locked ? "Gesperrt — tippen zum Senden" : "Nach oben schieben zum Sperren";
    }

    function hideHint() {
        const hint = document.getElementById("recordingHint");
        if (hint) hint.remove();
    }

    // --- Recognition Events ---
    recognition.onresult = (event) => {
        for (let i = event.resultIndex; i < event.results.length; i++) {
            if (event.results[i].isFinal) {
                fullTranscript += " " + event.results[i][0].transcript;
            }
        }
    };

    recognition.onend = () => {
        // Auto-restart wenn wir noch aufnehmen (Pause erkannt aber User will weitersprechen)
        if (!intentionalStop && (recordingMode === "holding" || recordingMode === "locked")) {
            try { recognition.start(); } catch(e) {}
            return;
        }

        // Intentional stop — verarbeiten
        intentionalStop = false;
        const mode = recordingMode;
        recordingMode = "idle";
        micBtn.classList.remove("recording", "locked");
        hideHint();
        stopTimer();

        const text = fullTranscript.trim();
        fullTranscript = "";

        if (text) {
            const input = document.getElementById("chatInput");
            input.value = (input.value + " " + text).trim();
            input.style.height = "auto";
            input.style.height = Math.min(input.scrollHeight, 120) + "px";
            // Auto-senden
            setTimeout(sendMessage, 150);
        }
    };

    recognition.onerror = (e) => {
        if (e.error === "no-speech" || e.error === "aborted") return;
        intentionalStop = false;
        recordingMode = "idle";
        micBtn.classList.remove("recording", "locked");
        hideHint();
        stopTimer();
        fullTranscript = "";
    };

    function stopRecording() {
        intentionalStop = true;
        recognition.stop();
    }

    function startRecording() {
        fullTranscript = "";
        intentionalStop = false;
        try { recognition.start(); } catch(e) {}
        startTimer();
    }

    // --- Mobile: Gedrückt halten ---
    micBtn.addEventListener("touchstart", (e) => {
        e.preventDefault();
        if (recordingMode === "locked") return;
        touchStartY = e.touches[0].clientY;
        recordingMode = "holding";
        micBtn.classList.add("recording");
        startRecording();
        showHint(false);
    }, { passive: false });

    micBtn.addEventListener("touchmove", (e) => {
        if (recordingMode !== "holding") return;
        const dy = e.touches[0].clientY - touchStartY;
        if (dy < -50) {
            recordingMode = "locked";
            micBtn.classList.add("locked");
            showHint(true);
        }
    }, { passive: true });

    micBtn.addEventListener("touchend", () => {
        if (recordingMode === "holding") {
            stopRecording(); // Loslassen = senden
        }
        // locked = weiter aufnehmen
    });

    // --- Desktop: Klick zum Starten/Senden ---
    micBtn.addEventListener("click", () => {
        if (recordingMode === "locked") {
            stopRecording();
        } else if (recordingMode === "idle") {
            recordingMode = "locked";
            micBtn.classList.add("recording", "locked");
            startRecording();
            showHint(true);
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
