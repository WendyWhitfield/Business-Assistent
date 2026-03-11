from flask import Flask, render_template, request, jsonify
from anthropic import Anthropic
from dotenv import load_dotenv
import os
import sqlite3
import json
from datetime import datetime

load_dotenv()

app = Flask(__name__)

# Absolute Pfade (wichtig für Railway/Gunicorn)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "assistant.db")
HUB_PATH = os.path.join(DATA_DIR, "hub.md")
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# --- Datenbank Setup ---
def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
        with open(HUB_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

def get_chat_history(section, limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT role, content FROM messages WHERE section=? ORDER BY id DESC LIMIT ?",
        (section, limit)
    )
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def save_message(section, role, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (section, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (section, role, content, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def save_todo(todo_type, text):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO todos (type, text, created) VALUES (?, ?, ?)",
        (todo_type, text, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_open_todos():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, type, text FROM todos WHERE done=0 ORDER BY created")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "type": r[1], "text": r[2]} for r in rows]

def complete_todo(todo_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE todos SET done=1 WHERE id=?", (todo_id,))
    conn.commit()
    conn.close()

def update_hub(new_content):
    try:
        with open(HUB_PATH, "r", encoding="utf-8") as f:
            current = f.read()
    except:
        current = ""
    updated = current + f"\n\n---\n[Update {datetime.now().strftime('%d.%m.%Y %H:%M')}]\n{new_content}"
    with open(HUB_PATH, "w", encoding="utf-8") as f:
        f.write(updated)

def save_session_summary(section):
    """Fasst das letzte Gespräch einer Section zusammen und speichert es im Hub."""
    history = get_chat_history(section, limit=20)
    if not history or len(history) < 2:
        return
    history_text = "\n".join([
        f"{'Wendy' if m['role'] == 'user' else 'Gwen'}: {m['content'][:400]}"
        for m in history[-10:]
    ])
    summary_prompt = f"""Fasse dieses Gespräch aus dem Bereich "{section}" in 2-4 Sätzen zusammen.
Was wurde besprochen, entschieden oder geplant? Schreib in Ich-Form (als Gwen) damit ich mich beim nächsten Gespräch erinnern kann.
Nur die Zusammenfassung, kein Präambel.

{history_text}"""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=250,
            messages=[{"role": "user", "content": summary_prompt}]
        )
        summary = response.content[0].text.strip()
        now = datetime.now().strftime('%d.%m.%Y %H:%M')
        update_hub(f"[Gesprächs-Erinnerung | {section} | {now}]\n{summary}")
    except:
        pass


def auto_extract_and_save(section, user_message, assistant_message):
    """Extrahiert wichtige Infos und speichert automatisch im Hub."""
    extract_prompt = f"""Analysiere dieses kurze Gespräch aus dem Bereich "{section}".

Nutzerin: {user_message}
Assistent: {assistant_message}

Gibt es WICHTIGE neue Informationen die dauerhaft gespeichert werden sollen?
Speichere NUR: Entscheidungen, neue Brand-Erkenntnisse, konkrete Pläne, wichtige Infos über die Person/Business.
NICHT speichern: Small Talk, Fragen ohne Antwort, allgemeine Überlegungen.

Antworte NUR mit validen JSON (kein Markdown, kein Text darum):
{{"save": true/false, "content": "Kurze Zusammenfassung was gespeichert wird (leer wenn save=false)", "todos": ["To-Do Text falls erwähnt"]}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": extract_prompt}]
        )
        result = json.loads(response.content[0].text)
        saved = False
        if result.get("save") and result.get("content"):
            update_hub(f"[{section}] {result['content']}")
            saved = True
        for todo in result.get("todos", []):
            if todo.strip():
                save_todo("auto", todo)
        return saved
    except:
        return False


# --- System Prompts je Bereich ---
SECTION_PROMPTS = {
    "home": """Du bist Gwen, Wendys persönliche Business-Assistentin, und begrüßt sie wenn sie die App öffnet.

Schreib eine kurze, menschliche Begrüßung — wie eine gute Freundin die genau weiß wo Wendy gerade steht.

Was rein muss (aber nie als Aufzählung — immer als fließender Text):
- Eine herzliche, variierende Begrüßung (nie immer dasselbe)
- Was gerade konkret ansteht oder wichtig ist (aus Hub und To-Dos, max. 2-3 Dinge)
- Eine offene Frage am Ende — was will sie heute angehen?

Der Ton ist wie eine WhatsApp-Nachricht von einer Assistentin die mitdenkt. Warm, direkt, auf den Punkt. Maximal 6-8 Sätze.""",
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
    "check-in": """Du eröffnest Wendys Tag. Wenn sie die App öffnet, startet sie hier.

Deine Aufgabe beim ersten Öffnen:
1. Begrüße sie kurz und menschlich — variierend, nie gleich
2. Sag ihr in 2-3 Punkten was heute konkret ansteht (aus Hub + To-Dos)
3. Stell ihr dann eine offene Frage: "Was nimmst du dir heute vor?" oder ähnlich — damit sie selbst spiegeln kann was sie plant

Wenn sie antwortet und ihren Plan teilt: bestätige kurz, ergänze wenn sinnvoll, und lass sie loslegen.
Das ist kein langes Coaching — das ist ein kurzes, energetisierendes Eröffnungsritual. Max. 6-8 Sätze für die Begrüßung.""",
    "check-out": "Du begleitest Wendys Tages-Abschluss. Was war gut? Was bleibt offen? Was kommt morgen? Du speicherst To-Do's für morgen automatisch.",
    "todos-morgen": "Du zeigst Wendys To-Do's für morgen und hilfst sie zu priorisieren.",
    "todos-woche": "Du zeigst Wendys Wochen-To-Do's, hilfst priorisieren und erinnerst an Offenes.",
    "woechentliche-reflexion": "Du führst Wendys Wochenreview. Was lief gut? Was nicht? Was nimmst du mit? Welche To-Do's blieben offen?",
    "monatliche-reflexion": "Du führst Wendys Monatsreview. Zahlen, Erkenntnisse, Entwicklung, nächster Monat.",
    "quartalsreflexion": "Du führst Wendys Quartalsbilanz. Ziele erreicht? Was hat sich verändert? Kurs korrigieren?",
    "jahresreflexion": "Du führst Wendys Jahresabschluss. Vollständige Bilanz: was wurde erreicht, was nicht, wie war das Jahr wirklich.",
}

BASE_SYSTEM = """Du bist Gwen (Gwendoline) — Wendys persönliche Business-Assistentin. Du kennst sie vollständig — ihre Geschichte, ihre Stimme, ihre Ziele, ihr Business.

WICHTIG:
- Du antwortest IMMER in Wendys Brand Voice: direkt, warm, authentisch, kein Marketing-Blabla
- Dein Name ist Gwen (kurz für Gwendoline) — du bist Wendys persönliche Assistentin
- Du bist kein generisches KI-Tool — du bist IHR Assistent
- Du erinnerst dich an alles was im Hub steht — das ist dein Gedächtnis
- Wichtige Erkenntnisse und Entscheidungen werden automatisch gespeichert

SCHREIBSTIL — ABSOLUT WICHTIG:
- KEIN Markdown. Keine Sternchen (**), keine Rauten (##), keine Bindestriche als Aufzählung
- Schreib wie ein Mensch der eine WhatsApp-Nachricht schreibt — fließend, mit natürlichen Absätzen
- Variiere deine Begrüßungen und die Struktur — nie zweimal genau gleich
- Reagiere auf den Kontext: Ist heute ein besonderer Tag (Weihnachten, Geburtstag, Montag nach dem Wochenende)? Dann fließt das natürlich ein.
- Absätze durch Leerzeilen trennen — das ist deine einzige Formatierung

HUB — was du über Wendy weißt:
{hub}

OFFENE TO-DO'S:
{todos}
"""

def build_system(section):
    hub = get_hub_content()
    todos = get_open_todos()
    todos_text = "\n".join([f"- [{t['type']}] {t['text']}" for t in todos]) if todos else "Keine offenen To-Do's"
    section_instruction = SECTION_PROMPTS.get(section, "Du hilfst Wendy in diesem Bereich.")
    # .replace() statt .format() — verhindert KeyError wenn hub.md geschweifte Klammern enthält
    system = BASE_SYSTEM.replace("{hub}", hub).replace("{todos}", todos_text)
    return system + f"\n\nDEIN FOKUS IN DIESEM BEREICH:\n{section_instruction}"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/section-start", methods=["POST"])
def section_start():
    """Generiert eine kontextbewusste Begrüßung — frisch oder als Fortsetzung."""
    data = request.json
    section = data.get("section", "business-strategie")

    system_prompt = build_system(section)
    history = get_chat_history(section, limit=10)

    hub = get_hub_content()
    hat_erinnerung = f"Gesprächs-Erinnerung | {section}" in hub

    now = datetime.now()
    stunde = now.hour
    if stunde < 12:
        tageszeit = "Guten Morgen"
    elif stunde < 17:
        tageszeit = "Hallo"
    else:
        tageszeit = "Guten Abend"

    if section == "check-in":
        # Check-In ist immer eine frische Tages-Eröffnung
        start_prompt = f"""{tageszeit} Wendy — sie startet gerade ihren Tag und öffnet die App.
Folge deinem Check-In Fokus: kurze Begrüßung, was heute ansteht, dann offene Frage damit sie ihren Plan spiegeln kann."""
    elif hat_erinnerung:
        start_prompt = f"""Wendy öffnet wieder den Bereich "{section}".
Im Hub findest du eine Gesprächs-Erinnerung von eurem letzten Gespräch hier.
Knüpfe kurz daran an — kein "Guten Morgen" nochmal, kein Wochentag. Zeig dass du dich erinnerst, frag womit sie weitermachen will. Max. 2-3 Sätze."""
    else:
        start_prompt = f"""{tageszeit} Wendy — sie öffnet den Bereich "{section}".
Begrüße sie kurz. Was ist hier gerade wichtig? Maximal 3-4 Sätze. Warm und direkt."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=system_prompt,
            messages=[{"role": "user", "content": start_prompt}]
        )
        welcome = response.content[0].text
        save_message(section, "assistant", welcome)
        return jsonify({"message": welcome})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    section = data.get("section", "business-strategie")
    user_message = data.get("message", "")

    image_data = data.get("image")
    image_type = data.get("image_type", "image/jpeg")

    if not user_message and not image_data:
        return jsonify({"error": "Keine Nachricht"}), 400

    system_prompt = build_system(section)
    history = get_chat_history(section)

    if image_data:
        user_content = [
            {"type": "image", "source": {"type": "base64", "media_type": image_type, "data": image_data}},
            {"type": "text", "text": user_message or "Was siehst du auf diesem Bild? Analysiere es im Kontext meines Business."}
        ]
    else:
        user_content = user_message

    messages = history + [{"role": "user", "content": user_content}]

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system_prompt,
        messages=messages
    )

    assistant_message = response.content[0].text

    save_message(section, "user", user_message)
    save_message(section, "assistant", assistant_message)

    # Automatisch wichtige Infos extrahieren und im Hub speichern
    saved = auto_extract_and_save(section, user_message, assistant_message)

    return jsonify({"response": assistant_message, "auto_saved": saved})


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

@app.route("/api/session-save", methods=["POST"])
def session_save():
    """Speichert Gesprächszusammenfassung im Hub wenn Section verlassen wird."""
    data = request.json
    section = data.get("section")
    if section:
        save_session_summary(section)
    return jsonify({"status": "ok"})


@app.route("/api/history/<section>", methods=["GET"])
def get_history(section):
    """Gibt die letzten 30 gespeicherten Nachrichten einer Section zurück."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT role, content, timestamp FROM messages WHERE section=? ORDER BY id DESC LIMIT 30",
        (section,)
    )
    rows = c.fetchall()
    conn.close()
    messages = [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in reversed(rows)]
    return jsonify({"messages": messages})


@app.route("/api/hub", methods=["GET"])
def get_hub():
    return jsonify({"content": get_hub_content()})

@app.route("/api/hub/update", methods=["POST"])
def hub_update():
    data = request.json
    content = data.get("content", "")
    if content:
        update_hub(content)
    return jsonify({"status": "ok"})


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
