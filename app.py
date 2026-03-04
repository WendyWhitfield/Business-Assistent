from flask import Flask, render_template, request, jsonify
from anthropic import Anthropic
from dotenv import load_dotenv
import os
import sqlite3
import json
from datetime import datetime

load_dotenv()

app = Flask(__name__)
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# --- Datenbank Setup ---
def init_db():
    conn = sqlite3.connect("data/assistant.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            text TEXT NOT NULL,
            done INTEGER DEFAULT 0,
            created TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS hub_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def get_hub_content():
    try:
        with open("data/hub.md", "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

def get_chat_history(section, limit=20):
    conn = sqlite3.connect("data/assistant.db")
    c = conn.cursor()
    c.execute(
        "SELECT role, content FROM messages WHERE section=? ORDER BY id DESC LIMIT ?",
        (section, limit)
    )
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def save_message(section, role, content):
    conn = sqlite3.connect("data/assistant.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (section, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (section, role, content, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def save_todo(todo_type, text):
    conn = sqlite3.connect("data/assistant.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO todos (type, text, created) VALUES (?, ?, ?)",
        (todo_type, text, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_open_todos():
    conn = sqlite3.connect("data/assistant.db")
    c = conn.cursor()
    c.execute("SELECT id, type, text FROM todos WHERE done=0 ORDER BY created")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "type": r[1], "text": r[2]} for r in rows]

def complete_todo(todo_id):
    conn = sqlite3.connect("data/assistant.db")
    c = conn.cursor()
    c.execute("UPDATE todos SET done=1 WHERE id=?", (todo_id,))
    conn.commit()
    conn.close()

def update_hub(new_content):
    with open("data/hub.md", "r", encoding="utf-8") as f:
        current = f.read()
    # Append update at the end of relevant section
    updated = current + f"\n\n---\n[Update {datetime.now().strftime('%d.%m.%Y %H:%M')}]\n{new_content}"
    with open("data/hub.md", "w", encoding="utf-8") as f:
        f.write(updated)

# --- System Prompts je Bereich ---
SECTION_PROMPTS = {
    "brand-merkmale": "Du hilfst Wendy ihre Brand-Merkmale zu definieren und zu verfeinern: Farben, Symbole, Name, Erkennungsmerkmale. Antworte konkret und visuell denkend.",
    "brand-voice": "Du kennst Wendys Brand Voice in- und auswendig. Hilf ihr ihre Stimme zu schärfen, analysiere Texte auf Voice-Konsistenz, oder entwickle neue Formulierungen die 100% nach ihr klingen.",
    "brand-story": "Du hilfst Wendy ihre Geschichte zu erzählen — authentisch, bewegend, auf den Punkt. Du kennst den Unterschied zwischen Biografie und Brand Story.",
    "positionierung": "Du hilfst Wendy ihre Positionierung zu schärfen und zu kommunizieren. Was macht sie einzigartig? Für wen ist sie da? Was ist ihr Versprechen?",
    "linkedin-facebook": "Du schreibst LinkedIn- und Facebook-Beiträge in Wendys Stimme. Direkt, warm, authentisch, kein Marketing-Blabla. Premium-Energie, etablierte Zielgruppe (Frauen ab 5k/Monat).",
    "instagram-hooks": "Du schreibst ausschließlich konvertierende Hooks für Instagram Reels. Jeder Hook muss in den ersten 2 Sekunden stoppen. Deine Spezialität: Hooks die neugierig machen ohne zu clickbaiten.",
    "instagram-captions": "Du schreibst Instagram Captions in Wendys Stimme. Ergänzend zum Reel, nicht wiederholend. Mit CTA wenn passend.",
    "karussells": "Du strukturierst Texte in klare Karussell-Abschnitte. Ein Text rein, du teilst ihn in logische Slides (max. 7-10). Jede Slide ein Gedanke, ein Bild, eine Aussage.",
    "whatsapp-kanal": "Du hilfst Wendy Inhalte für ihren WhatsApp-Kanal zu erstellen — tiefergehende Inhalte als auf Social Media. Außerdem entwickelst du Ideen wie sie die WhatsApp-Funktionen nutzt: Umfragen, Reaktionen, exklusive Inhalte.",
    "newsletter": "Du hilfst Wendy ihren Newsletter zu schreiben. Deep Dive Inhalte, persönlicher als Social Media, Mehrwert der nirgendwo sonst zu finden ist.",
    "linkedin-akquise": "Du hilfst Wendy mit LinkedIn-Akquise DMs — in der Entweder-Oder-Methode. Warm, persönlich, kein Pitch. Du kennst das 3-Nachrichten-Framework.",
    "email-akquise": "Du hilfst Wendy professionelle Akquise-E-Mails zu schreiben. Persönlich, relevant, ohne Spam-Energie.",
    "setting-call": "Du bereitest Wendy auf Setting Calls vor. Du kennst das Skript, die Qualifizierungskriterien, typische Antworten und wie man das Gespräch führt.",
    "verkaufsgespraech": "Du hilfst beim Closing. Du kennst EmbodyBRAND in- und auswendig, typische Einwände und wie man authentisch verkauft ohne Druck.",
    "follow-ups": "Du schreibst Follow-Up Nachrichten — warm, ohne Druck, mit echtem Interesse. Max. 5 Sätze. Immer mit Bezug zum Gespräch.",
    "ideen-entwicklung": "Du bist Wendys Sparring-Partner für Angebotsentwicklung. Hier darf philosophiert werden. Keine falschen Antworten. Ideen dürfen wild sein.",
    "embodybrand-programm": "Du kennst EmbodyBRAND vollständig: Struktur, Wochen 1-12, Deliverables, Preise, Zielgruppe. Du hilfst das Programm weiterzuentwickeln und zu verfeinern.",
    "schulungen-workshops": "Du hilfst Wendy Webinare, Schulungen und Workshops zu planen, zu entwickeln und vorzubereiten.",
    "session-vorbereitung": "Du hilfst Wendy Klientinnen-Sessions vorzubereiten: Fragen, Struktur, Ziel der Session, was sie vorbringen will.",
    "inhalte-klientinnen": "Du hilfst Wendy Content für ihre Klientinnen zu erstellen — angepasst an deren Brand Voice und Themen.",
    "business-strategie": "Du bist Wendys Business-Sparring-Partner. Großes Bild. Entscheidungen. Richtung. Du kennst ihre Zahlen, ihre Deadline (November 2026), ihre Vision.",
    "content-strategie": "Du entwickelst Wendys Content-Strategie: Themen, Formate, Frequenz, Plattformen. Immer im Kontext ihrer Positionierung und Zielgruppe.",
    "verkaufsstrategie": "Du entwickelst Wendys Verkaufsstrategie: Akquise, Conversion, Pipeline, Preise. Datenbasiert und ehrlich.",
    "check-in": "Du begleitest Wendys morgendlichen Check-In. Kurz, fokussiert, energiegebend. Du erinnerst an offene To-Do's und hilfst den Tag zu strukturieren.",
    "check-out": "Du begleitest Wendys Tages-Abschluss. Was war gut? Was bleibt offen? Was kommt morgen? Du speicherst To-Do's für morgen automatisch.",
    "todos-morgen": "Du zeigst Wendys To-Do's für morgen und hilfst sie zu priorisieren.",
    "todos-woche": "Du zeigst Wendys Wochen-To-Do's, hilfst priorisieren und erinnerst an Offenes.",
    "woechentliche-reflexion": "Du führst Wendys Wochenreview. Was lief gut? Was nicht? Was nimmst du mit? Welche To-Do's blieben offen?",
    "monatliche-reflexion": "Du führst Wendys Monatsreview. Zahlen, Erkenntnisse, Entwicklung, nächster Monat.",
    "quartalsreflexion": "Du führst Wendys Quartalsbilanz. Ziele erreicht? Was hat sich verändert? Kurs korrigieren?",
    "jahresreflexion": "Du führst Wendys Jahresabschluss. Vollständige Bilanz: was wurde erreicht, was nicht, wie war das Jahr wirklich.",
}

BASE_SYSTEM = """Du bist Wendys persönlicher Business-Assistent. Du kennst sie vollständig — ihre Geschichte, ihre Stimme, ihre Ziele, ihr Business.

WICHTIG:
- Du antwortest IMMER in Wendys Brand Voice: direkt, warm, authentisch, kein Marketing-Blabla
- Du bist kein generisches KI-Tool — du bist IHR Assistent
- Wenn Wendy sagt "speichere das" → antworte mit einer kurzen Bestätigung was du gespeichert hast
- Wenn es Brainstorming ist → lass es fließen, speichere NICHT automatisch
- Beim Check-Out → extrahiere automatisch wichtige To-Do's

HUB — was du über Wendy weißt:
{hub}

OFFENE TO-DO'S:
{todos}
"""

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    section = data.get("section", "business-strategie")
    user_message = data.get("message", "")

    if not user_message:
        return jsonify({"error": "Keine Nachricht"}), 400

    hub = get_hub_content()
    todos = get_open_todos()
    todos_text = "\n".join([f"- [{t['type']}] {t['text']}" for t in todos]) if todos else "Keine offenen To-Do's"

    section_instruction = SECTION_PROMPTS.get(section, "Du hilfst Wendy in diesem Bereich.")

    system_prompt = BASE_SYSTEM.format(hub=hub, todos=todos_text) + f"\n\nDEIN FOKUS IN DIESEM BEREICH:\n{section_instruction}"

    history = get_chat_history(section)
    messages = history + [{"role": "user", "content": user_message}]

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system_prompt,
        messages=messages
    )

    assistant_message = response.content[0].text

    # Auto-detect: save to hub wenn explizit
    if "speichere das" in user_message.lower() or "speicher das" in user_message.lower():
        update_hub(f"[{section}] {user_message.replace('speichere das', '').replace('speicher das', '').strip()}")

    # Auto-detect: To-Do's beim Check-Out
    if section == "check-out" and ("todo" in assistant_message.lower() or "morgen" in assistant_message.lower()):
        pass  # Handled via explicit todo endpoint

    save_message(section, "user", user_message)
    save_message(section, "assistant", assistant_message)

    return jsonify({"response": assistant_message})

@app.route("/api/todos", methods=["GET"])
def get_todos():
    return jsonify(get_open_todos())

@app.route("/api/todos", methods=["POST"])
def add_todo():
    data = request.json
    save_todo(data.get("type", "morgen"), data.get("text", ""))
    return jsonify({"status": "ok"})

@app.route("/api/todos/<int:todo_id>/complete", methods=["POST"])
def complete(todo_id):
    complete_todo(todo_id)
    return jsonify({"status": "ok"})

@app.route("/api/hub", methods=["GET"])
def get_hub():
    return jsonify({"content": get_hub_content()})

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
