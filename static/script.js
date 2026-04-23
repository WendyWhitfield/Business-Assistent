// === STATE ===
let currentSection = "check-in";
let previousSection = null;
let checkinDone = false;
let isRecording = false;
let recognition = null;
let pendingImage = null; // { base64, type, name }
let useSonnet = false; // Standard: Haiku (günstig). Sonnet auf Anfrage.

// === INIT ===
document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initInput();
    initVoice();
    initHub();
    initMobileMenu();
    initImageUpload();
    initDocUpload();
    initModelToggle();
    switchSection("check-in", "Check-In");
});

// Beim Schließen/Wechseln des Tabs automatisch speichern
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
        saveCurrentSession();
    }
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

async function saveCurrentSession() {
    if (!currentSection || currentSection === "home") return;
    try {
        await fetch("/api/session-save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ section: currentSection })
        });
    } catch(e) {}
}

async function switchSection(section, label) {
    // Aktuelles Gespräch im Hub speichern bevor gewechselt wird
    await saveCurrentSession();

    previousSection = currentSection;
    if (currentSection === "check-in") checkinDone = true;
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
            body: JSON.stringify({ section, previousSection, checkinDone })
        });
        if (!res.ok) {
            const errText = await res.text();
            throw new Error(`HTTP ${res.status}: ${errText.slice(0, 200)}`);
        }
        const data = await res.json();
        typing.remove();
        if (!data.skip) {
            appendMessage("assistant", data.message, false);
        }
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
        const timeout = setTimeout(() => controller.abort(), 120000);

        const body = { section: currentSection, message: text, sonnet: useSonnet };
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
            showSaveIndicator(data.saved_items);
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

const SAVE_ICONS = { meilenstein: "🏆", info: "💾", hub_update: "📝", todo: "✅", ziel: "🎯", notiz: "💡", verbindung: "🔗" };
const SAVE_LABELS = { meilenstein: "Meilenstein", info: "Gespeichert", hub_update: "Hub aktualisiert", todo: "To-Do", ziel: "Ziel", notiz: "Notiz", verbindung: "Verbindung" };

function showSaveIndicator(savedItems) {
    if (!savedItems || savedItems.length === 0) return;
    const messages = document.getElementById("chatMessages");
    const card = document.createElement("div");
    card.className = "memory-save-card";
    card.innerHTML = savedItems.map(item =>
        `<span class="save-item"><span class="save-icon">${SAVE_ICONS[item.type] || "💾"}</span><strong>${SAVE_LABELS[item.type] || "Gespeichert"}:</strong> ${item.text.slice(0, 80)}${item.text.length > 80 ? "…" : ""}</span>`
    ).join("");
    messages.appendChild(card);
    setTimeout(() => card.style.opacity = "0.4", 5000);
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
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        micBtn.style.display = "none";
        return;
    }

    let recordingMode = "idle"; // idle, holding, locked
    let touchStartY = 0;
    let touchMoved = false;
    let fullTranscript = "";
    let timerInterval = null;
    let timerSeconds = 0;
    let activeRec = null; // aktuelle Recognition-Instanz

    // --- Timer ---
    function startTimer() {
        timerSeconds = 0;
        updateTimer();
        timerInterval = setInterval(() => { timerSeconds++; updateTimer(); }, 1000);
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
        hint.textContent = locked ? "Antippen zum Senden" : "Nach oben schieben zum Sperren";
    }
    function hideHint() {
        const hint = document.getElementById("recordingHint");
        if (hint) hint.remove();
    }

    // --- Neue Recognition-Instanz starten (kein continuous — verhindert Chrome-Replay-Bug) ---
    function startSession() {
        const rec = new SpeechRecognition();
        rec.lang = "de-DE";
        rec.continuous = false;
        rec.interimResults = false;
        rec.maxAlternatives = 1;
        activeRec = rec;

        rec.onresult = (event) => {
            for (let i = 0; i < event.results.length; i++) {
                if (event.results[i].isFinal) {
                    fullTranscript += " " + event.results[i][0].transcript;
                }
            }
        };

        rec.onend = () => {
            if (activeRec !== rec) return; // veraltete Instanz ignorieren
            if (recordingMode === "holding" || recordingMode === "locked") {
                // Weiter aufnehmen — neue Instanz starten
                setTimeout(startSession, 100);
            }
        };

        rec.onerror = (e) => {
            if (e.error === "no-speech" || e.error === "aborted" || e.error === "network") return;
            finishRecording();
        };

        try { rec.start(); } catch(e) {}
    }

    function finishRecording() {
        recordingMode = "idle";
        micBtn.classList.remove("recording", "locked");
        hideHint();
        stopTimer();
        if (activeRec) {
            try { activeRec.stop(); } catch(e) {}
            activeRec = null;
        }
        // Kurz warten damit letztes onresult noch feuern kann
        setTimeout(() => {
            const text = fullTranscript.trim();
            fullTranscript = "";
            if (text) {
                const input = document.getElementById("chatInput");
                input.value = (input.value + " " + text).trim();
                input.style.height = "auto";
                input.style.height = Math.min(input.scrollHeight, 120) + "px";
                sendMessage();
            }
        }, 300);
    }

    function startRecording() {
        fullTranscript = "";
        startSession();
        startTimer();
    }

    // --- Mobile Touch ---
    micBtn.addEventListener("touchstart", (e) => {
        e.preventDefault(); // verhindert Ghost-Click nach touchend
        touchMoved = false;
        if (recordingMode === "locked") return;
        if (recordingMode === "holding") return;
        touchStartY = e.touches[0].clientY;
        recordingMode = "holding";
        micBtn.classList.add("recording");
        startRecording();
        showHint(false);
    }, { passive: false });

    micBtn.addEventListener("touchmove", (e) => {
        if (recordingMode !== "holding") return;
        touchMoved = true;
        const dy = e.touches[0].clientY - touchStartY;
        if (dy < -50) {
            recordingMode = "locked";
            micBtn.classList.add("locked");
            showHint(true);
        }
    }, { passive: true });

    micBtn.addEventListener("touchend", (e) => {
        e.preventDefault(); // verhindert Ghost-Click
        if (recordingMode === "holding") {
            finishRecording();
        } else if (recordingMode === "locked" && !touchMoved) {
            finishRecording(); // kurzer Tap = senden
        }
        touchMoved = false;
    });

    // --- Desktop Klick ---
    micBtn.addEventListener("click", () => {
        if (recordingMode === "locked") {
            finishRecording();
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
    const hubEditBtn = document.getElementById("hubEditBtn");
    const hubSaveBtn = document.getElementById("hubSaveBtn");
    const hubCancelBtn = document.getElementById("hubCancelBtn");
    const hubContent = document.getElementById("hubContent");
    const hubEditor = document.getElementById("hubEditor");
    const hubTextarea = document.getElementById("hubTextarea");

    hubEditBtn.addEventListener("click", () => {
        hubContent.style.display = "none";
        hubEditor.style.display = "flex";
        hubTextarea.value = hubContent.dataset.raw || "";
        hubTextarea.focus();
    });

    hubCancelBtn.addEventListener("click", () => {
        hubEditor.style.display = "none";
        hubContent.style.display = "block";
    });

    hubSaveBtn.addEventListener("click", async () => {
        const content = hubTextarea.value.trim();
        if (!content) return;
        hubSaveBtn.textContent = "Speichert...";
        hubSaveBtn.disabled = true;
        try {
            await fetch(`/api/memory/${activeTab}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content })
            });
            hubContent.dataset.raw = content;
            if (activeTab === "hub") {
                hubContent.innerHTML = renderMarkdown(content);
            } else {
                hubContent.textContent = content;
            }
            hubEditor.style.display = "none";
            hubContent.style.display = "block";
        } catch(e) {
            alert("Fehler beim Speichern.");
        } finally {
            hubSaveBtn.textContent = "Speichern";
            hubSaveBtn.disabled = false;
        }
    });

    // Tabs
    let activeTab = "hub";
    const editableTabs = ["hub", "goals", "notizen"];
    const hubSearch = document.getElementById("hubSearch");
    document.querySelectorAll(".mem-tab").forEach(tab => {
        tab.addEventListener("click", async () => {
            document.querySelectorAll(".mem-tab").forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            activeTab = tab.dataset.tab;
            hubEditor.style.display = "none";

            if (activeTab === "suche") {
                hubContent.style.display = "none";
                hubSearch.style.display = "block";
                hubEditBtn.style.display = "none";
                document.getElementById("searchInput").focus();
            } else {
                hubSearch.style.display = "none";
                hubContent.style.display = "block";
                hubEditBtn.style.display = editableTabs.includes(activeTab) ? "inline-block" : "none";
                await loadMemoryTab(activeTab);
            }
        });
    });

    hubToggle.addEventListener("click", async () => {
        hubPanel.classList.toggle("open");
        if (hubPanel.classList.contains("open")) {
            await loadHub();
        }
    });

    hubClose.addEventListener("click", () => {
        hubPanel.classList.remove("open");
    });

    // Suche
    const searchBtn = document.getElementById("searchBtn");
    const searchInput = document.getElementById("searchInput");
    const searchResults = document.getElementById("searchResults");

    async function runSearch() {
        const query = searchInput.value.trim();
        if (!query) return;
        searchResults.innerHTML = "<p style='color:#888;font-size:13px'>Suche läuft…</p>";
        try {
            const res = await fetch("/api/search", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query })
            });
            const data = await res.json();
            if (!data.results || data.results.length === 0) {
                searchResults.innerHTML = "<p style='color:#888;font-size:13px'>Nichts gefunden.</p>";
                return;
            }
            searchResults.innerHTML = data.results.map(r => `
                <div class="search-result">
                    <div class="search-result-source">${escapeHtml(r.source)}</div>
                    <div class="search-result-text">${escapeHtml(r.text)}</div>
                </div>
            `).join("");
        } catch(e) {
            searchResults.innerHTML = "<p style='color:#c00;font-size:13px'>Fehler bei der Suche.</p>";
        }
    }

    searchBtn.addEventListener("click", runSearch);
    searchInput.addEventListener("keydown", e => {
        if (e.key === "Enter") runSearch();
    });
}

async function loadMemoryTab(key) {
    const hubContent = document.getElementById("hubContent");
    hubContent.textContent = "Lädt...";
    try {
        const res = await fetch(`/api/memory/${key}`);
        const data = await res.json();
        const text = data.content || "(noch leer)";
        hubContent.dataset.raw = text;
        if (key === "hub") {
            hubContent.innerHTML = renderMarkdown(text);
        } else {
            hubContent.textContent = text;
        }
    } catch(e) {
        hubContent.textContent = "Fehler beim Laden.";
    }
}

async function loadHub() {
    const hubContent = document.getElementById("hubContent");
    try {
        const res = await fetch("/api/hub");
        const data = await res.json();
        hubContent.dataset.raw = data.content || "";
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

// === DOCUMENT UPLOAD ===
function initDocUpload() {
    const docBtn = document.getElementById("docBtn");
    const docInput = document.getElementById("docInput");
    if (!docBtn || !docInput) return;

    docBtn.addEventListener("click", () => docInput.click());

    docInput.addEventListener("change", async () => {
        const file = docInput.files[0];
        if (!file) return;
        docInput.value = "";

        const formData = new FormData();
        formData.append("file", file);

        docBtn.disabled = true;
        docBtn.style.opacity = "0.5";

        try {
            const res = await fetch("/api/parse-document", { method: "POST", body: formData });
            const data = await res.json();
            if (data.error) {
                appendMessage("assistant", "Dokument konnte nicht geladen werden: " + data.error, false);
                return;
            }
            // Inhalt direkt ins Textarea schreiben — kein JS-State nötig
            const input = document.getElementById("chatInput");
            const label = data.summarized
                ? `[Zusammenfassung von: ${data.filename}]\n\n${data.text}\n\n`
                : `[Dokument: ${data.filename}]\n\n${data.text}\n\n`;
            input.value = label + input.value;
            input.style.height = "auto";
            input.style.height = Math.min(input.scrollHeight, 120) + "px";
            input.focus();
        } catch(e) {
            appendMessage("assistant", "Fehler beim Hochladen des Dokuments.", false);
        } finally {
            docBtn.disabled = false;
            docBtn.style.opacity = "1";
        }
    });
}

// === MODEL TOGGLE ===
function initModelToggle() {
    const btn = document.getElementById("modelToggle");
    if (!btn) return;
    btn.addEventListener("click", () => {
        useSonnet = !useSonnet;
        btn.textContent = useSonnet ? "S" : "H";
        btn.title = useSonnet
            ? "Sonnet aktiv (stark & komplex) — klicken für Haiku"
            : "Haiku aktiv (schnell & günstig) — klicken für Sonnet";
        btn.classList.toggle("sonnet-active", useSonnet);
    });
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
