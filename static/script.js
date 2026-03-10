// === STATE ===
let currentSection = "business-strategie";
let isRecording = false;
let recognition = null;
let pendingImage = null; // { base64, type, name }

// === INIT ===
document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initInput();
    initVoice();
    initHub();
    initMobileMenu();
    initImageUpload();
    switchSection("home", "Let's do this! 🤍");
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

    const messages = document.getElementById("chatMessages");
    messages.innerHTML = "";

    // Alte Nachrichten laden
    try {
        const histRes = await fetch(`/api/history/${section}`);
        if (histRes.ok) {
            const histData = await histRes.json();
            if (histData.messages && histData.messages.length > 0) {
                const sep = document.createElement("div");
                sep.className = "history-separator";
                sep.textContent = "— frühere Nachrichten —";
                messages.appendChild(sep);
                histData.messages.forEach(m => {
                    appendMessage(m.role, m.content, false);
                });
                const sep2 = document.createElement("div");
                sep2.className = "history-separator";
                sep2.textContent = "— jetzt —";
                messages.appendChild(sep2);
            }
        }
    } catch(e) {}

    const typing = appendTyping();

    // Neue Begrüßung holen
    try {
        const res = await fetch("/api/section-start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ section })
        });
        if (!res.ok) {
            const errText = await res.text();
            throw new Error(`HTTP ${res.status}: ${errText.slice(0, 200)}`);
        }
        const data = await res.json();
        typing.remove();
        appendMessage("assistant", data.message, false);
    } catch (err) {
        console.error("section-start Fehler:", err);
        typing.remove();
        appendMessage("assistant", `Verbindungsfehler beim Laden — bitte Seite neu laden. (${err.message})`, false);
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
    if (!text && !pendingImage) return;

    input.value = "";
    input.style.height = "auto";

    // Nachricht anzeigen
    if (pendingImage) {
        appendImageMessage("user", pendingImage.previewUrl, text);
    } else {
        appendMessage("user", text);
    }

    const imageToSend = pendingImage ? { base64: pendingImage.base64, type: pendingImage.type } : null;
    clearImagePreview();

    const typing = appendTyping();

    try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 60000);

        const body = { section: currentSection, message: text };
        if (imageToSend) {
            body.image = imageToSend.base64;
            body.image_type = imageToSend.type;
        }

        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
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

function appendImageMessage(role, previewUrl, caption) {
    const messages = document.getElementById("chatMessages");
    const div = document.createElement("div");
    div.className = `message ${role}`;
    const now = new Date();
    const time = now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    div.innerHTML = `
        <div class="message-bubble">
            <img src="${previewUrl}" style="max-width:200px;max-height:200px;border-radius:8px;display:block;margin-bottom:${caption ? "6px" : "0"}">
            ${caption ? `<span>${escapeHtml(caption)}</span>` : ""}
        </div>
        <div class="message-time">${time}</div>
    `;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\n/g, "<br>");
}

// Einfaches Markdown → HTML (für Hub-Panel)
function renderMarkdown(md) {
    return md
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        // Headings
        .replace(/^#### (.+)$/gm, "<h4>$1</h4>")
        .replace(/^### (.+)$/gm, "<h3>$1</h3>")
        .replace(/^## (.+)$/gm, "<h2>$1</h2>")
        .replace(/^# (.+)$/gm, "<h2>$1</h2>")
        // Bold
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        // Horizontal rule
        .replace(/^---$/gm, "<hr>")
        // Table rows (simple: | a | b | → row)
        .replace(/^\|(.+)\|$/gm, (_, cells) => {
            const tds = cells.split("|").map(c => `<td>${c.trim()}</td>`).join("");
            return `<tr>${tds}</tr>`;
        })
        // Table separator rows (|---|---|) → skip
        .replace(/<tr>(<td>-+<\/td>)+<\/tr>/g, "")
        // Wrap consecutive <tr> in <table>
        .replace(/((<tr>.+<\/tr>\n?)+)/g, "<table>$1</table>")
        // List items
        .replace(/^- (.+)$/gm, "<li>$1</li>")
        .replace(/(<li>.+<\/li>\n?)+/g, "<ul>$&</ul>")
        // Line breaks (non-tag lines)
        .replace(/\n(?!<)/g, "<br>\n")
        // Clean up extra breaks after block elements
        .replace(/(<\/h[2-4]>|<\/hr>|<\/table>|<\/ul>)<br>/g, "$1");
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
        // Auto-restart wenn wir noch aufnehmen
        if (!intentionalStop && (recordingMode === "holding" || recordingMode === "locked")) {
            setTimeout(() => {
                try { recognition.start(); } catch(e) {}
            }, 150);
            return;
        }

        // Intentional stop — verarbeiten
        intentionalStop = false;
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
            setTimeout(sendMessage, 150);
        }
    };

    recognition.onerror = (e) => {
        // Für diese Fehler einfach weiter aufnehmen (onend übernimmt den Neustart)
        if (e.error === "no-speech" || e.error === "aborted" || e.error === "network") return;
        // Echter Fehler — alles zurücksetzen
        intentionalStop = true;
        recordingMode = "idle";
        micBtn.classList.remove("recording", "locked");
        hideHint();
        stopTimer();
        fullTranscript = "";
    };

    function stopRecording() {
        intentionalStop = true;
        try { recognition.stop(); } catch(e) {
            // Recognition war gerade nicht aktiv — onend manuell triggern
            intentionalStop = false;
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
                setTimeout(sendMessage, 150);
            }
        }
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

    let touchMoved = false;
    micBtn.addEventListener("touchstart", (e) => {
        touchMoved = false;
    }, { passive: true, capture: true });

    micBtn.addEventListener("touchmove", (e) => {
        touchMoved = true;
    }, { passive: true, capture: true });

    micBtn.addEventListener("touchend", (e) => {
        if (recordingMode === "holding") {
            stopRecording(); // Loslassen = senden
        } else if (recordingMode === "locked" && !touchMoved) {
            stopRecording(); // Kurzer Tap im gesperrten Modus = senden
        }
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
        hubContent.innerHTML = renderMarkdown(data.content);
    } catch {
        hubContent.textContent = "Hub konnte nicht geladen werden.";
    }
}

// === IMAGE UPLOAD ===
function initImageUpload() {
    const imageBtn = document.getElementById("imageBtn");
    const imageInput = document.getElementById("imageInput");
    if (!imageBtn || !imageInput) return;

    imageBtn.addEventListener("click", () => imageInput.click());

    imageInput.addEventListener("change", () => {
        const file = imageInput.files[0];
        if (!file) return;
        imageInput.value = "";

        const reader = new FileReader();
        reader.onload = (e) => {
            const dataUrl = e.target.result;
            // dataUrl = "data:image/jpeg;base64,XXXXX"
            const [meta, base64] = dataUrl.split(",");
            const type = meta.match(/:(.*?);/)[1];
            pendingImage = { base64, type, previewUrl: dataUrl, name: file.name };
            showImagePreview(dataUrl);
        };
        reader.readAsDataURL(file);
    });
}

function showImagePreview(url) {
    // Altes Preview entfernen
    clearImagePreview();
    const area = document.querySelector(".chat-input-area");
    const preview = document.createElement("div");
    preview.className = "image-preview";
    preview.id = "imagePreview";
    preview.innerHTML = `
        <img src="${url}" alt="Vorschau">
        <button class="image-preview-remove" id="imagePreviewRemove" title="Entfernen">✕</button>
    `;
    area.insertBefore(preview, area.firstChild);
    document.getElementById("imagePreviewRemove").addEventListener("click", clearImagePreview);
}

function clearImagePreview() {
    pendingImage = null;
    const el = document.getElementById("imagePreview");
    if (el) el.remove();
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
