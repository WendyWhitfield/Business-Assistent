from flask import Flask, render_template, request, jsonify
from anthropic import Anthropic
from dotenv import load_dotenv
import os
import sqlite3
import json
import re
from datetime import datetime
import calendar
try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:
    from datetime import timezone, timedelta
    BERLIN = timezone(timedelta(hours=1))  # Fallback CET

def now_berlin():
    return datetime.now(BERLIN)

load_dotenv()

app = Flask(__name__)

# --- Konfiguration (via .env oder Railway-Variablen anpassbar) ---
CLIENT_NAME = os.environ.get("CLIENT_NAME", "Wendy")
ASSISTANT_NAME = os.environ.get("ASSISTANT_NAME", "Gwen")
SHOW_EMBODYBRAND = os.environ.get("SHOW_EMBODYBRAND", "true").lower() == "true"

# Absolute Pfade (wichtig für Railway/Gunicorn)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DEFAULTS_DIR = os.path.join(BASE_DIR, "defaults")
DB_PATH = os.path.join(DATA_DIR, "assistant.db")
HUB_PATH = os.path.join(DATA_DIR, "hub.md")
ALLTAG_PATH = os.path.join(DATA_DIR, "alltag.md")
GOALS_PATH = os.path.join(DATA_DIR, "goals.md")
MILESTONES_PATH = os.path.join(DATA_DIR, "milestones.md")
ARCHIVE_PATH = os.path.join(DATA_DIR, "archive.md")
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
    # Persistentes Gedächtnis — überlebt jeden Redeploy
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    _migrate_files_to_db()

def _mem_get(key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM memory WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else ""

def _mem_set(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO memory (key, value, updated) VALUES (?, ?, ?)",
              (key, value, now_berlin().isoformat()))
    conn.commit()
    conn.close()

def _migrate_files_to_db():
    """Seed-Fallback: Nur wenn DB leer ist — schreibt NIEMALS über vorhandene Daten.
    defaults/hub.md ist der Fallback wenn Volume leer ist."""
    for key, path in [("hub", HUB_PATH), ("alltag", ALLTAG_PATH),
                      ("goals", GOALS_PATH), ("milestones", MILESTONES_PATH), ("archive", ARCHIVE_PATH)]:
        if _mem_get(key):
            continue  # Bereits in DB — NICHT überschreiben
        default_path = os.path.join(DEFAULTS_DIR, os.path.basename(path))
        for try_path in [default_path, path]:  # defaults zuerst (immer aktuell in Git)
            try:
                with open(try_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if content.strip():
                    _mem_set(key, content)
                    break
            except:
                continue

def get_hub_content():
    return _mem_get("hub")

def get_alltag_content():
    return _mem_get("alltag")

def get_milestones_content():
    return _mem_get("milestones")

def get_archive_content():
    return _mem_get("archive")

def get_notizen_content():
    return _mem_get("notizen")

def get_verbindungen_content():
    return _mem_get("verbindungen")

def add_notiz(tag, text):
    """Hängt eine neue Notiz/Gedanke an — mit Datum und optionalem Tag."""
    date = now_berlin().strftime('%d.%m.%Y')
    tag_clean = tag.strip() if tag else "allgemein"
    entry = f"[{date} | {tag_clean}]\n{text}\n"
    current = _mem_get("notizen") or "# NOTIZEN\n\n"
    _mem_set("notizen", current + "\n---\n" + entry)

def add_verbindung(text):
    """Speichert eine erkannte Verbindung zwischen Themen."""
    date = now_berlin().strftime('%d.%m.%Y')
    entry = f"[{date}] {text}\n"
    current = _mem_get("verbindungen") or "# VERBINDUNGEN\n\n"
    _mem_set("verbindungen", current + entry)

def get_archive_for_review(section):
    """Gibt relevante Archiv-Einträge für den jeweiligen Rückblick zurück."""
    content = get_archive_content()
    if not content.strip():
        return ""
    now = now_berlin()

    if section == "monatliche-reflexion":
        # Aktueller Monat + letzter Monat
        cutoff = now.replace(day=1)
        if cutoff.month == 1:
            cutoff = cutoff.replace(year=cutoff.year - 1, month=12)
        else:
            cutoff = cutoff.replace(month=cutoff.month - 1)
        label = f"Monat {now.strftime('%B %Y')}"
    elif section == "quartalsreflexion":
        # Letztes Quartal (3 Monate)
        months_back = 3
        cutoff = now.replace(month=max(1, now.month - months_back), day=1)
        label = f"Quartal (letzte 3 Monate)"
    elif section == "jahresreflexion":
        # Letztes Jahr
        cutoff = now.replace(year=now.year - 1, month=1, day=1)
        label = f"Jahr {now.year}"
    else:
        return ""

    # Einträge filtern: Format [KWxx | DD.MM.YYYY]
    filtered = []
    for block in re.split(r'\n(?=\[KW)', content):
        match = re.match(r'\[KW\d+ \| (\d{2})\.(\d{2})\.(\d{4})\]', block)
        if match:
            entry_date = datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            if entry_date >= datetime(cutoff.year, cutoff.month, cutoff.day):
                filtered.append(block.strip())

    if not filtered:
        return ""
    return f"\n\nARCHIV — {label}:\n" + "\n\n".join(filtered)

def add_milestone(text):
    """Fügt einen Meilenstein hinzu — bleibt für immer, eine Zeile."""
    date = now_berlin().strftime('%d.%m.%Y')
    entry = f"[{date}] {text}\n"
    current = _mem_get("milestones") or "# MEILENSTEINE\n\n"
    _mem_set("milestones", current + entry)

def get_goals_content():
    return _mem_get("goals")

def save_goals(goal_type, goals_text):
    """Ersetzt Ziele eines Typs komplett — keine Anhäufung, nur das Aktuelle bleibt."""
    content = _mem_get("goals") or "# ZIELE\n"
    date = now_berlin().strftime('%d.%m.%Y')
    new_section = f"[{goal_type} | {date}]\n{goals_text}"
    pattern = rf'\[{re.escape(goal_type)} \| [^\]]+\]\n[^\[]*'
    if re.search(pattern, content):
        content = re.sub(pattern, new_section + "\n\n", content)
    else:
        content = content.rstrip() + f"\n\n---\n{new_section}"
    _mem_set("goals", content)

def clear_goals(goal_type):
    """Löscht Ziele eines Typs wenn sie erledigt sind."""
    content = _mem_get("goals")
    if not content:
        return
    pattern = rf'\n*---\n\[{re.escape(goal_type)} \| [^\]]+\]\n[^\[]*'
    _mem_set("goals", re.sub(pattern, "", content))

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

def get_chat_history_today(section, max_per_message=800):
    """Lädt ALLE Nachrichten von heute in dieser Section.
    Kürzt sehr lange Nachrichten damit der Kontext nicht überläuft.
    Fallback auf letzte 60 wenn zu viele Nachrichten."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = now_berlin().strftime('%Y-%m-%d')
    c.execute(
        "SELECT role, content FROM messages WHERE section=? AND timestamp LIKE ? ORDER BY id",
        (section, f"{today}%")
    )
    rows = c.fetchall()
    conn.close()
    # Sicherheitsnetz: maximal 80 Nachrichten
    if len(rows) > 80:
        rows = rows[-80:]
    result = []
    for role, content in rows:
        if len(content) > max_per_message:
            content = content[:max_per_message] + "…"
        result.append({"role": role, "content": content})
    return result

def save_message(section, role, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (section, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (section, role, content, now_berlin().isoformat())
    )
    conn.commit()
    conn.close()

def save_todo(todo_type, text):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO todos (type, text, created) VALUES (?, ?, ?)",
        (todo_type, text, now_berlin().isoformat())
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
    current = _mem_get("hub") or ""
    updated = current + f"\n\n---\n[Update {now_berlin().strftime('%d.%m.%Y %H:%M')}]\n{new_content}"
    _mem_set("hub", updated)

def replace_section_memory(section, summary):
    """Ersetzt die Erinnerung einer Section im Alltag-Hub — bleibt erhalten, wird nur aktualisiert."""
    content = _mem_get("alltag") or "# ALLTAG-HUB\n"
    now = now_berlin().strftime('%d.%m.%Y %H:%M')
    new_entry = f"[{section} | {now}]\n{summary}"
    pattern = rf'\[{re.escape(section)} \| [^\]]+\]\n[^\[]*'
    if re.search(pattern, content):
        content = re.sub(pattern, new_entry + "\n\n", content)
    else:
        content = content.rstrip() + f"\n\n---\n{new_entry}"
    _mem_set("alltag", content)


def save_session_summary(section):
    """Fasst das letzte Gespräch einer Section zusammen und speichert es im Hub (ersetzt altes)."""
    history = get_chat_history(section, limit=20)
    if not history or len(history) < 2:
        return
    history_text = "\n".join([
        f"{'Wendy' if m['role'] == 'user' else 'Gwen'}: {m['content'][:400]}"
        for m in history[-10:]
    ])
    summary_prompt = f"""Fasse dieses Gespräch aus dem Bereich "{section}" in 2-4 Sätzen zusammen.
Was wurde besprochen, entschieden oder geplant? Was ist der nächste Schritt?
Schreib in Ich-Form (als Gwen) damit ich mich beim nächsten Gespräch erinnern kann.
Nur die Zusammenfassung, kein Präambel.

{history_text}"""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=250,
            messages=[{"role": "user", "content": summary_prompt}]
        )
        summary = response.content[0].text.strip()
        replace_section_memory(section, summary)
    except:
        pass


def has_messages_today(section):
    """Prüft ob es heute schon Nachrichten in dieser Section gibt."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = now_berlin().strftime('%Y-%m-%d')
    c.execute(
        "SELECT COUNT(*) FROM messages WHERE section=? AND timestamp LIKE ?",
        (section, f"{today}%")
    )
    count = c.fetchone()[0]
    conn.close()
    return count > 0


def get_periodic_reminders():
    """Gibt kontextbezogene Erinnerungen basierend auf dem aktuellen Datum zurück."""
    now = now_berlin()
    reminders = []

    # Montag → Wochenziele
    if now.weekday() == 0:
        reminders.append("WOCHENBEGINN (Montag): Erinnere Wendy heute beim Check-In daran, ihre Wochenziele festzulegen — was will sie diese Woche erreichen?")

    # Freitag → Wochenreflexion
    if now.weekday() == 4:
        reminders.append("WOCHENENDE (Freitag): Erinnere Wendy heute daran, die Woche zu reflektieren — was lief gut, was nicht, was nimmt sie mit? Das gehört in den Wachstums-Bereich (woechentliche-reflexion).")

    last_day = calendar.monthrange(now.year, now.month)[1]

    # Letzter Tag des Monats → Monats-Review
    if now.day == last_day:
        reminders.append(f"MONATSENDE: Heute ist der letzte Tag des Monats ({now.strftime('%d.%m.%Y')}). Erinnere Wendy ans Monats-Review und daran, Ziele für den nächsten Monat festzulegen.")

    # Erster Tag des Monats → Monatsziele setzen
    if now.day == 1:
        reminders.append(f"MONATSBEGINN: Heute startet ein neuer Monat ({now.strftime('%B %Y')}). Erinnere Wendy daran, ihre Monatsziele festzulegen.")

    # Quartalsende (31. März, 30. Juni, 30. Sep, 31. Dez)
    quarter_end = {3: 31, 6: 30, 9: 30, 12: 31}
    if now.month in quarter_end and now.day == quarter_end[now.month]:
        reminders.append("QUARTALSENDE: Heute endet das Quartal. Erinnere Wendy ans Quartals-Review — was wurde erreicht, was bleibt, was kommt?")

    # Quartalsbeginn (1. Jan, Apr, Jul, Okt)
    if now.month in [1, 4, 7, 10] and now.day == 1:
        reminders.append("QUARTALSBEGINN: Heute startet ein neues Quartal. Erinnere Wendy daran, ihre Quartalsziele festzulegen.")

    # Jahresende
    if now.month == 12 and now.day == 31:
        reminders.append("JAHRESENDE: Heute ist der 31. Dezember — das Jahr endet. Erinnere Wendy ans große Jahres-Review.")

    # Jahresbeginn
    if now.month == 1 and now.day == 1:
        reminders.append("JAHRESBEGINN: Heute ist der 1. Januar — ein neues Jahr! Erinnere Wendy daran, ihre Jahresziele festzulegen.")

    return reminders


def compress_week_memories():
    """Komprimiert alle Section-Erinnerungen zu einer kompakten Wochen-Zusammenfassung.
    Wird freitags beim Check-In aufgerufen. Hält alltag.md schlank."""
    alltag = get_alltag_content()
    if not alltag.strip() or alltag.count("[") < 3:
        return  # Nicht genug zum Komprimieren
    now = now_berlin()
    kw = now.isocalendar()[1]
    prompt = f"""Fasse diese Arbeits-Erinnerungen aus verschiedenen Bereichen kompakt zusammen.
Max. 6-8 Sätze gesamt. Was wurde diese Woche hauptsächlich gemacht, entschieden, erreicht?
Schreib in Ich-Form (als Gwen). Nur die Zusammenfassung, kein Präambel.

{alltag}"""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        summary = response.content[0].text.strip()
        entry = f"[KW{kw} | {now.strftime('%d.%m.%Y')}]\n{summary}\n"
        # Alltag: nur aktuelle Woche — alte Details weg
        _mem_set("alltag", f"# ALLTAG-HUB\n\n---\n{entry}")
        # Archiv: Woche anhängen — bleibt dauerhaft für Rückblicke
        archive = _mem_get("archive") or "# ARCHIV\n\n"
        _mem_set("archive", archive + "\n" + entry)
    except:
        pass

def cleanup_hub_memories():
    """Beim Check-In: Freitags wird der Alltag-Hub zur Wochen-Zusammenfassung komprimiert."""
    now = now_berlin()
    if now.weekday() == 4:  # Freitag
        compress_week_memories()


# --- Gwen's Tools (Anthropic Tool Use) ---
GWEN_TOOLS = [
    {
        "name": "im_hub_speichern",
        "description": "Speichert eine wichtige Information dauerhaft im Hub. Nutze das für: neue Erkenntnisse, Entscheidungen, Strategien, Status-Updates, Klientinnen-Infos, Angebots-Änderungen, Preise, Pläne.",
        "input_schema": {
            "type": "object",
            "properties": {
                "inhalt": {
                    "type": "string",
                    "description": "Die Information in einem klaren, vollständigen Satz"
                }
            },
            "required": ["inhalt"]
        }
    },
    {
        "name": "hub_abschnitt_aktualisieren",
        "description": "Aktualisiert oder überschreibt einen Abschnitt im Hub wenn eine ältere Info überholt ist — z.B. Klientinnen-Status, aktueller Angebotspreis, laufende Kampagne.",
        "input_schema": {
            "type": "object",
            "properties": {
                "abschnitt": {
                    "type": "string",
                    "description": "Kurze Bezeichnung des Abschnitts (z.B. 'Klientinnen-Status', 'Akquise', 'Angebot EmbodyBRAND')"
                },
                "inhalt": {
                    "type": "string",
                    "description": "Der neue, aktualisierte Inhalt"
                }
            },
            "required": ["abschnitt", "inhalt"]
        }
    },
    {
        "name": "todo_hinzufuegen",
        "description": "Fügt eine konkrete Aufgabe zur To-Do-Liste hinzu.",
        "input_schema": {
            "type": "object",
            "properties": {
                "aufgabe": {
                    "type": "string",
                    "description": "Die konkrete Aufgabe"
                },
                "typ": {
                    "type": "string",
                    "enum": ["morgen", "diese-woche", "auto"],
                    "description": "Zeitrahmen: 'morgen', 'diese-woche', oder 'auto'"
                }
            },
            "required": ["aufgabe"]
        }
    },
    {
        "name": "ziel_setzen",
        "description": "Setzt oder aktualisiert ein Ziel. Nur wenn Wendy explizit ein Ziel festlegt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "typ": {
                    "type": "string",
                    "enum": ["täglich", "wöchentlich", "monatlich", "quartalsweise", "jährlich"]
                },
                "inhalt": {
                    "type": "string",
                    "description": "Das Ziel als klarer Text"
                }
            },
            "required": ["typ", "inhalt"]
        }
    },
    {
        "name": "meilenstein_hinzufuegen",
        "description": "Fügt einen echten Meilenstein hinzu. Nur für besondere Ereignisse: erste Klientin gewonnen, erfolgreicher Launch, großes Ziel erreicht.",
        "input_schema": {
            "type": "object",
            "properties": {
                "meilenstein": {
                    "type": "string",
                    "description": "Der Meilenstein in einem prägnanten Satz"
                }
            },
            "required": ["meilenstein"]
        }
    },
    {
        "name": "notiz_speichern",
        "description": "Speichert einen Gedanken, eine Idee oder Beobachtung im Notizbuch — mit einem Themen-Tag. Nutze das für: Ideen die noch nicht spruchreif sind, spontane Beobachtungen, Inspirationen, persönliche Erkenntnisse, Content-Ideen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": "Themen-Tag (z.B. 'Content-Idee', 'Positionierung', 'Klientin', 'Persönlich', 'Strategie')"
                },
                "inhalt": {
                    "type": "string",
                    "description": "Der Gedanke oder die Idee im vollen Wortlaut"
                }
            },
            "required": ["tag", "inhalt"]
        }
    },
    {
        "name": "verbindung_notieren",
        "description": "Notiert eine erkannte Verbindung zwischen zwei Themen, Ideen oder Mustern. Nutze das wenn du Zusammenhänge siehst die für Wendy relevant sind — z.B. ein Muster das sich wiederholt, oder eine Verbindung zwischen ihrer Biografie und ihrem Business.",
        "input_schema": {
            "type": "object",
            "properties": {
                "verbindung": {
                    "type": "string",
                    "description": "Die Verbindung klar beschrieben: Was hängt womit zusammen, und warum ist das relevant?"
                }
            },
            "required": ["verbindung"]
        }
    }
]


def execute_tool(name, input_data):
    """Führt ein Gwen-Tool aus und gibt Preview + Bestätigung zurück."""
    if name == "im_hub_speichern":
        inhalt = input_data.get("inhalt", "")
        update_hub(inhalt)
        return {"type": "info", "preview": inhalt, "message": f"Im Hub gespeichert."}

    elif name == "hub_abschnitt_aktualisieren":
        abschnitt = input_data.get("abschnitt", "Allgemein")
        inhalt = input_data.get("inhalt", "")
        update_hub(f"[{abschnitt} — aktualisiert {now_berlin().strftime('%d.%m.%Y')}] {inhalt}")
        return {"type": "hub_update", "preview": f"{abschnitt}: {inhalt}", "message": f"Abschnitt '{abschnitt}' aktualisiert."}

    elif name == "todo_hinzufuegen":
        aufgabe = input_data.get("aufgabe", "")
        typ = input_data.get("typ", "auto")
        save_todo(typ, aufgabe)
        return {"type": "todo", "preview": aufgabe, "message": f"To-Do hinzugefügt."}

    elif name == "ziel_setzen":
        typ = input_data.get("typ", "wöchentlich")
        inhalt = input_data.get("inhalt", "")
        save_goals(typ, inhalt)
        return {"type": "ziel", "preview": f"{typ}: {inhalt}", "message": f"Ziel gesetzt."}

    elif name == "meilenstein_hinzufuegen":
        meilenstein = input_data.get("meilenstein", "")
        add_milestone(meilenstein)
        return {"type": "meilenstein", "preview": meilenstein, "message": f"Meilenstein gespeichert."}

    elif name == "notiz_speichern":
        tag = input_data.get("tag", "allgemein")
        inhalt = input_data.get("inhalt", "")
        add_notiz(tag, inhalt)
        return {"type": "notiz", "preview": f"[{tag}] {inhalt}", "message": f"Notiz gespeichert."}

    elif name == "verbindung_notieren":
        verbindung = input_data.get("verbindung", "")
        add_verbindung(verbindung)
        return {"type": "verbindung", "preview": verbindung, "message": f"Verbindung notiert."}

    return {"type": "unknown", "preview": "", "message": "Unbekanntes Tool"}


def run_with_tools(system_prompt, messages, model):
    """Chat-Loop mit Tool Use. Gibt (assistant_text, saved_items) zurück."""
    saved_items = []
    current_messages = list(messages)

    while True:
        response = client.messages.create(
            model=model,
            max_tokens=8096,
            system=system_prompt,
            messages=current_messages,
            tools=GWEN_TOOLS
        )

        if response.stop_reason == "tool_use":
            # Assistenten-Antwort (mit Tool-Calls) als Dicts in History schreiben
            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input
                    })
            current_messages.append({"role": "assistant", "content": assistant_content})

            # Tools ausführen und Ergebnisse sammeln
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input)
                    if result["preview"]:
                        saved_items.append({"type": result["type"], "text": result["preview"]})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result["message"]
                    })

            current_messages.append({"role": "user", "content": tool_results})

        else:
            # Fertig — finalen Text zurückgeben
            text = "".join(block.text for block in response.content if hasattr(block, "text"))
            return text, saved_items


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
    "gedanken": """Du bist Wendys Notizbuch und Gedankenfänger. Hier darf alles rein — roh, unfertig, halbgar.
Deine Aufgabe: Gedanken empfangen, kurz spiegeln, mit notiz_speichern festhalten.
Dann aktiv nach Verbindungen suchen: "Das klingt nach dem was du am [Datum] über [Thema] gesagt hast — stimmt das?"
Kein langer Chat — kurze Bestätigung, dann speichern. Der Fokus liegt auf dem Festhalten, nicht auf dem Ausarbeiten.
Wenn Wendy einen Gedanken teilt der eindeutig mit etwas aus Hub oder Verbindungen zusammenhängt: nutze verbindung_notieren.""",
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

BASE_SYSTEM = """Du bist {assistant_name} — {client_name}s persönliche Business-Assistentin. Du kennst sie vollständig — ihre Geschichte, ihre Stimme, ihre Ziele, ihr Business.

AKTUELLES DATUM & UHRZEIT (Berliner Zeit — immer korrekt verwenden!):
{datum}

WICHTIG:
- Du antwortest IMMER in {client_name}s Brand Voice: direkt, warm, authentisch, kein Marketing-Blabla
- Dein Name ist {assistant_name} — du bist {client_name}s persönliche Assistentin
- Du bist kein generisches KI-Tool — du bist IHR Assistent
- Du erinnerst dich an alles was in beiden Hubs steht — das ist dein Gedächtnis

DEINE TOOLS — PROAKTIV NUTZEN:
Du hast Werkzeuge mit denen du direkt das Gedächtnis schreiben kannst. Nutze sie aktiv — warte nicht bis du gefragt wirst.
- im_hub_speichern: Für neue Erkenntnisse, Entscheidungen, Status-Updates, Strategien, alles was dauerhaft relevant ist. Im Zweifel: speichern.
- hub_abschnitt_aktualisieren: Wenn du weißt dass eine ältere Info überholt ist (z.B. neue Klientin, Preisänderung, neuer Status).
- todo_hinzufuegen: Wenn ein konkreter nächster Schritt genannt wird.
- ziel_setzen: Nur wenn {client_name} explizit ein Ziel formuliert.
- meilenstein_hinzufuegen: Nur für wirklich besondere Ereignisse (erste Klientin, Launch, großer Abschluss).
Du kannst mehrere Tools in einem Schritt aufrufen. {client_name} sieht direkt was du gespeichert hast.

SCHREIBSTIL — ABSOLUT WICHTIG:
- KEIN Markdown. Keine Sternchen (**), keine Rauten (##), keine Bindestriche als Aufzählung
- Schreib wie ein Mensch der eine WhatsApp-Nachricht schreibt — fließend, mit natürlichen Absätzen
- Variiere deine Begrüßungen und die Struktur — nie zweimal genau gleich
- Reagiere auf den Kontext: Ist heute ein besonderer Tag (Weihnachten, Geburtstag, Montag nach dem Wochenende)? Dann fließt das natürlich ein.
- Absätze durch Leerzeilen trennen — das ist deine einzige Formatierung

TAGESRHYTHMUS — WICHTIG:
{client_name} hat einen festen Check-In/Check-Out-Rhythmus. Wenn sie sich verabschiedet (z.B. "tschüss", "bis morgen", "gute nacht", "ciao", "ich mache Schluss", "ich bin fertig für heute", "bis dann", "muss weg", "feierabend" oder ähnliches), erinnere sie sanft aber klar daran zum Check-Out zu wechseln. Beispiel: "Bevor du gehst — wechsel kurz in den Check-Out, damit wir den Tag zusammenfassen und den Plan für morgen festhalten."

KERN-HUB — feste Infos über {client_name} (Identität, Angebot, Ziele, Entscheidungen):
{hub}

ALLTAG-HUB — wo zuletzt gearbeitet wurde, was gerade läuft:
{alltag}

OFFENE TO-DO'S:
{todos}

AKTUELLE ZIELE (täglich / wöchentlich / monatlich / quartalsweise / jährlich):
{goals}
Wenn neue Ziele festgelegt werden, ersetzen sie die alten — nichts häuft sich an.

MEILENSTEINE — was {client_name} bereits erreicht hat (dauerhaft, wächst langsam):
{milestones}

NOTIZEN & GEDANKEN — spontane Ideen, Beobachtungen, noch nicht fertig gedacht:
{notizen}

ERKANNTE VERBINDUNGEN — Muster und Zusammenhänge die du bereits notiert hast:
{verbindungen}

SECOND BRAIN — DEINE AUFGABE:
Du bist nicht nur Assistentin — du bist auch Wendys aktives Gedächtnis.
Das bedeutet: Wenn du in einem Gespräch etwas hörst das mit etwas aus Notizen, Hub oder früheren Gesprächen zusammenhängt — sag es. Aktiv. Nicht auf Anfrage.
Beispiel: "Das klingt nach dem was du letzten Monat über deine Zielgruppe notiert hast — soll ich die Verbindung zeigen?"
Nutze notiz_speichern großzügig — auch für halbfertige Gedanken. Notizen dürfen roh sein.
Nutze verbindung_notieren wenn du ein echtes Muster erkennst. Nicht bei jeder Kleinigkeit — aber wenn du denkst: "Das hängt zusammen."
"""

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

def build_system(section):
    hub = get_hub_content()
    alltag = get_alltag_content()
    goals = get_goals_content()
    milestones = get_milestones_content()
    notizen = get_notizen_content()
    verbindungen = get_verbindungen_content()
    todos = get_open_todos()
    todos_text = "\n".join([f"- [{t['type']}] {t['text']}" for t in todos]) if todos else "Keine offenen To-Do's"
    goals_text = goals if goals.strip() else "Noch keine Ziele festgelegt."
    milestones_text = milestones if milestones.strip() else "Noch keine Meilensteine eingetragen."
    notizen_text = notizen if notizen and notizen.strip() else "Noch keine Notizen."
    verbindungen_text = verbindungen if verbindungen and verbindungen.strip() else "Noch keine Verbindungen erkannt."
    section_instruction = SECTION_PROMPTS.get(section, "Du hilfst Wendy in diesem Bereich.")

    now = now_berlin()
    wochentag = WOCHENTAGE[now.weekday()]
    datum_text = f"{wochentag}, {now.strftime('%d.%m.%Y')} — {now.strftime('%H:%M')} Uhr (Berliner Zeit)"

    system = BASE_SYSTEM.replace("{hub}", hub).replace("{alltag}", alltag).replace("{todos}", todos_text).replace("{goals}", goals_text).replace("{milestones}", milestones_text).replace("{notizen}", notizen_text).replace("{verbindungen}", verbindungen_text)
    system = system.replace("{datum}", datum_text)
    system = system.replace("{client_name}", CLIENT_NAME).replace("{assistant_name}", ASSISTANT_NAME)
    # Für Rückblick-Sections: relevantes Archiv dazu laden
    archive_context = ""
    if section in ["monatliche-reflexion", "quartalsreflexion", "jahresreflexion"]:
        archive_context = get_archive_for_review(section)
    full = system + f"\n\nDEIN FOKUS IN DIESEM BEREICH:\n{section_instruction}{archive_context}"
    # Namen in Section-Prompts ersetzen (für Client-Deployments)
    if CLIENT_NAME != "Wendy":
        full = full.replace("Wendy", CLIENT_NAME)
    if ASSISTANT_NAME != "Gwen":
        full = full.replace("Gwen", ASSISTANT_NAME).replace("Gwendoline", ASSISTANT_NAME)
    return full


@app.route("/")
def index():
    return render_template("index.html", assistant_name=ASSISTANT_NAME, client_name=CLIENT_NAME, show_embodybrand=SHOW_EMBODYBRAND)

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify({"assistant_name": ASSISTANT_NAME, "client_name": CLIENT_NAME})


@app.route("/api/section-start", methods=["POST"])
def section_start():
    """Generiert eine kontextbewusste Begrüßung — frisch oder als Fortsetzung."""
    data = request.json
    section = data.get("section", "business-strategie")
    previous_section = data.get("previousSection")
    checkin_done = data.get("checkinDone", False)

    # Heute schon in dieser Section gearbeitet → kein API-Call, einfach überspringen
    if has_messages_today(section):
        return jsonify({"skip": True})

    system_prompt = build_system(section)

    hub = get_hub_content()
    alltag = get_alltag_content()
    hat_erinnerung = f"[{section} |" in alltag

    now = now_berlin()
    stunde = now.hour
    if stunde < 12:
        tageszeit = "Guten Morgen"
    elif stunde < 17:
        tageszeit = "Hallo"
    else:
        tageszeit = "Guten Abend"

    if section == "check-in":
        # Hub aufräumen: alte Erinnerungen zu kompaktem Stand zusammenfassen
        cleanup_hub_memories()
        # Periodische Erinnerungen (Montag, Monatsende, etc.)
        periodic = get_periodic_reminders()
        periodic_text = "\n".join(periodic)
        extra = f"\n\nBESONDERE ERINNERUNGEN FÜR HEUTE:\n{periodic_text}" if periodic else ""
        # Check-In: immer frische Tages-Eröffnung
        start_prompt = f"""{tageszeit} Wendy — sie startet ihren Tag.
Folge deinem Check-In Fokus: kurze Begrüßung, was heute ansteht, dann offene Frage damit sie ihren Plan spiegeln kann.{extra}"""

    elif checkin_done or previous_section:
        # Wir sind mitten im Tag — kurzer natürlicher Übergang, kein Tages-Briefing
        hat_checkin_erinnerung = "[check-in |" in alltag
        checkin_kontext = "\nWICHTIG: Im Hub findest du die Gesprächs-Erinnerung vom Check-In heute — dort steht was Wendy heute vorhat und warum sie in diesen Bereich gewechselt ist. Nutze das als Kontext." if hat_checkin_erinnerung else ""

        if hat_erinnerung:
            start_prompt = f"""Wendy wechselt in den Bereich "{section}". Ihr habt hier schon mal gesprochen — im Hub ist eine Gesprächs-Erinnerung dazu.{checkin_kontext}
Sag kurz worum es hier zuletzt ging und was als nächstes anstand. Kein Tages-Briefing. Max. 2 Sätze."""
        else:
            start_prompt = f"""Wendy wechselt gerade von "{previous_section or 'Check-In'}" in "{section}".{checkin_kontext}
Knüpf direkt an das an was im Check-In besprochen wurde — zeig dass du weißt warum sie jetzt hier ist. Direkt in den Bereich einsteigen, keine allgemeine Begrüßung. Max. 2 Sätze."""

    elif hat_erinnerung:
        start_prompt = f"""Wendy öffnet wieder den Bereich "{section}". Im Hub ist eine Gesprächs-Erinnerung.
Knüpfe kurz daran an, frag womit sie weitermachen will. Max. 2-3 Sätze."""

    else:
        start_prompt = f"""{tageszeit} Wendy — sie öffnet den Bereich "{section}" zum ersten Mal.
Begrüße sie kurz, sag was hier möglich ist. Max. 3 Sätze. Warm und direkt."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
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
    use_sonnet = data.get("sonnet", False)
    model = "claude-sonnet-4-6" if use_sonnet else "claude-haiku-4-5-20251001"

    image_data = data.get("image")
    image_type = data.get("image_type", "image/jpeg")

    if not user_message and not image_data:
        return jsonify({"error": "Keine Nachricht"}), 400

    system_prompt = build_system(section)
    history = get_chat_history_today(section)

    if image_data:
        user_content = [
            {"type": "image", "source": {"type": "base64", "media_type": image_type, "data": image_data}},
            {"type": "text", "text": user_message or "Was siehst du auf diesem Bild? Analysiere es im Kontext meines Business."}
        ]
    else:
        user_content = user_message

    messages = history + [{"role": "user", "content": user_content}]

    assistant_message, saved_items = run_with_tools(system_prompt, messages, model)

    save_message(section, "user", user_message)
    save_message(section, "assistant", assistant_message)

    return jsonify({"response": assistant_message, "auto_saved": len(saved_items) > 0, "saved_items": saved_items})


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


@app.route("/api/goals", methods=["GET"])
def api_get_goals():
    return jsonify({"content": get_goals_content()})

@app.route("/api/goals", methods=["POST"])
def api_save_goals():
    data = request.json
    goal_type = data.get("type", "")
    content = data.get("content", "")
    if goal_type and content:
        save_goals(goal_type, content)
    return jsonify({"status": "ok"})

@app.route("/api/goals/clear", methods=["POST"])
def api_clear_goals():
    data = request.json
    goal_type = data.get("type", "")
    if goal_type:
        clear_goals(goal_type)
    return jsonify({"status": "ok"})


@app.route("/api/memory/<key>", methods=["GET"])
def get_memory_key(key):
    allowed = ["hub", "alltag", "goals", "milestones", "archive", "notizen", "verbindungen"]
    if key not in allowed:
        return jsonify({"error": "not found"}), 404
    return jsonify({"content": _mem_get(key) or ""})

@app.route("/api/memory/<key>", methods=["POST"])
def set_memory_key(key):
    allowed = ["hub", "alltag", "goals", "milestones", "notizen"]
    if key not in allowed:
        return jsonify({"error": "not allowed"}), 403
    data = request.json
    content = data.get("content", "")
    if content:
        _mem_set(key, content)
        # Hub-Edits auch in Datei schreiben — überlebt Volume-Resets via Git
        if key == "hub":
            try:
                with open(HUB_PATH, "w", encoding="utf-8") as f:
                    f.write(content)
            except:
                pass
    return jsonify({"status": "ok"})

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

@app.route("/api/hub/set", methods=["POST"])
def hub_set():
    """Setzt den Hub-Inhalt komplett (für initiales Befüllen durch Wendy)."""
    data = request.json
    content = data.get("content", "")
    if content:
        _mem_set("hub", content)
    return jsonify({"status": "ok"})


@app.route("/api/parse-document", methods=["POST"])
def parse_document():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "Keine Datei"}), 400

    filename = file.filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    try:
        if ext == "txt":
            text = file.read().decode("utf-8", errors="replace")
        elif ext == "pdf":
            import pypdf
            reader = pypdf.PdfReader(file)
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(p for p in pages if p.strip())
        elif ext == "docx":
            from docx import Document
            doc = Document(file)
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        else:
            return jsonify({"error": "Format nicht unterstützt. Bitte .txt, .pdf oder .docx."}), 400

        if not text.strip():
            return jsonify({"error": "Dokument ist leer oder konnte nicht gelesen werden."}), 400

        # Dokument zusammenfassen wenn länger als 1500 Zeichen
        if len(text) > 1500:
            summary_prompt = f"""Fasse dieses Dokument "{filename}" präzise zusammen.
Struktur:
- Was ist das für ein Dokument?
- Die wichtigsten Inhalte / Kernaussagen (max. 8 Punkte)
- Was könnte für Wendys Business relevant sein?

Halte die Zusammenfassung kompakt (max. 400 Wörter). Nur die Zusammenfassung, kein Präambel.

Dokumentinhalt:
{text[:8000]}"""
            try:
                sum_response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=600,
                    messages=[{"role": "user", "content": summary_prompt}]
                )
                summary = sum_response.content[0].text.strip()
                return jsonify({"text": summary, "filename": filename, "summarized": True, "original_length": len(text)})
            except:
                pass  # Fallback auf Original wenn Zusammenfassung fehlschlägt

        return jsonify({"text": text, "filename": filename, "summarized": False})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Lesen: {str(e)}"}), 500


@app.route("/api/search", methods=["POST"])
def search():
    data = request.json
    query = data.get("query", "").strip().lower()
    if not query or len(query) < 2:
        return jsonify({"results": []})

    terms = query.split()
    results = []

    sources = [
        ("Hub", _mem_get("hub")),
        ("Notizen", _mem_get("notizen")),
        ("Verbindungen", _mem_get("verbindungen")),
        ("Alltag", _mem_get("alltag")),
        ("Meilensteine", _mem_get("milestones")),
        ("Ziele", _mem_get("goals")),
    ]

    for source_name, content in sources:
        if not content:
            continue
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip() and len(p.strip()) > 10]
        for para in paragraphs:
            para_lower = para.lower()
            if all(term in para_lower for term in terms):
                results.append({
                    "source": source_name,
                    "text": para[:300] + ("…" if len(para) > 300 else "")
                })

    # Chat-Verlauf durchsuchen
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT section, role, content, timestamp FROM messages WHERE LOWER(content) LIKE ? ORDER BY id DESC LIMIT 8",
            (f"%{terms[0]}%",)
        )
        rows = c.fetchall()
        conn.close()
        for section, role, content, ts in rows:
            content_lower = content.lower()
            if all(term in content_lower for term in terms):
                date = ts[:10] if ts else ""
                results.append({
                    "source": f"Chat · {section} ({date})",
                    "text": content[:250] + ("…" if len(content) > 250 else "")
                })
    except:
        pass

    return jsonify({"results": results[:15]})


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
