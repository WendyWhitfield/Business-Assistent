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

# Absolute Pfade (wichtig für Railway/Gunicorn)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
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
    conn.commit()
    conn.close()

def get_hub_content():
    try:
        with open(HUB_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

def get_alltag_content():
    try:
        with open(ALLTAG_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

def get_milestones_content():
    try:
        with open(MILESTONES_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

def get_archive_content():
    try:
        with open(ARCHIVE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

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
    now = now_berlin().strftime('%d.%m.%Y')
    entry = f"[{now}] {text}\n"
    try:
        with open(MILESTONES_PATH, "r", encoding="utf-8") as f:
            current = f.read()
    except:
        current = "# MEILENSTEINE — Wendy Whitfield\n\n"
    with open(MILESTONES_PATH, "w", encoding="utf-8") as f:
        f.write(current + entry)

def get_goals_content():
    try:
        with open(GOALS_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

def save_goals(goal_type, goals_text):
    """Ersetzt Ziele eines Typs komplett — keine Anhäufung, nur das Aktuelle bleibt."""
    try:
        with open(GOALS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except:
        content = "# ZIELE — Wendy Whitfield\n"
    now = now_berlin().strftime('%d.%m.%Y')
    new_section = f"[{goal_type} | {now}]\n{goals_text}"
    pattern = rf'\[{re.escape(goal_type)} \| [^\]]+\]\n[^\[]*'
    if re.search(pattern, content):
        content = re.sub(pattern, new_section + "\n\n", content)
    else:
        content = content.rstrip() + f"\n\n---\n{new_section}"
    with open(GOALS_PATH, "w", encoding="utf-8") as f:
        f.write(content)

def clear_goals(goal_type):
    """Löscht Ziele eines Typs wenn sie erledigt sind."""
    try:
        with open(GOALS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except:
        return
    pattern = rf'\n*---\n\[{re.escape(goal_type)} \| [^\]]+\]\n[^\[]*'
    content = re.sub(pattern, "", content)
    with open(GOALS_PATH, "w", encoding="utf-8") as f:
        f.write(content)

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
    try:
        with open(HUB_PATH, "r", encoding="utf-8") as f:
            current = f.read()
    except:
        current = ""
    updated = current + f"\n\n---\n[Update {now_berlin().strftime('%d.%m.%Y %H:%M')}]\n{new_content}"
    with open(HUB_PATH, "w", encoding="utf-8") as f:
        f.write(updated)

def replace_section_memory(section, summary):
    """Ersetzt die Erinnerung einer Section im Alltag-Hub — bleibt erhalten, wird nur aktualisiert."""
    try:
        with open(ALLTAG_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except:
        content = "# ALLTAG-HUB — Wendy Whitfield\n"
    now = now_berlin().strftime('%d.%m.%Y %H:%M')
    new_entry = f"[{section} | {now}]\n{summary}"
    pattern = rf'\[{re.escape(section)} \| [^\]]+\]\n[^\[]*'
    if re.search(pattern, content):
        content = re.sub(pattern, new_entry + "\n\n", content)
    else:
        content = content.rstrip() + f"\n\n---\n{new_entry}"
    with open(ALLTAG_PATH, "w", encoding="utf-8") as f:
        f.write(content)


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
        # Alltag: nur aktuelle Woche
        with open(ALLTAG_PATH, "w", encoding="utf-8") as f:
            f.write(f"# ALLTAG-HUB — Wendy Whitfield\n\n---\n{entry}")
        # Archiv: Woche anhängen — bleibt für Rückblicke
        try:
            with open(ARCHIVE_PATH, "r", encoding="utf-8") as f:
                archive = f.read()
        except:
            archive = "# ARCHIV — Wendy Whitfield\n\n"
        with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
            f.write(archive + "\n" + entry)
    except:
        pass

def cleanup_hub_memories():
    """Beim Check-In: Freitags wird der Alltag-Hub zur Wochen-Zusammenfassung komprimiert."""
    now = now_berlin()
    if now.weekday() == 4:  # Freitag
        compress_week_memories()


def auto_extract_and_save(section, user_message, assistant_message):
    """Extrahiert wichtige Infos und speichert automatisch im Hub."""
    extract_prompt = f"""Analysiere dieses kurze Gespräch aus dem Bereich "{section}".

Nutzerin: {user_message}
Assistent: {assistant_message}

Antworte NUR mit validen JSON (kein Markdown, kein Text darum):
{{
  "meilenstein": "Nur wenn ein echter Meilenstein erreicht wurde (z.B. erste Klientin gewonnen, Launch, Umsatzziel erreicht, Programm abgeschlossen) — 1 kurzer Satz oder leer",
  "info": "Nur wenn eine dauerhafte Entscheidung oder wichtige Änderung am Business — sonst leer (kein Tages-Kram)",
  "todos": ["To-Do Text falls konkret erwähnt"],
  "ziele": {{
    "typ": "täglich|wöchentlich|monatlich|quartalsweise|jährlich — nur wenn im Gespräch explizit Ziele FESTGELEGT wurden, sonst leer",
    "inhalt": "Die Ziele als klarer Text — sonst leer",
    "erledigt": "täglich|wöchentlich|monatlich|quartalsweise|jährlich — nur wenn Ziele explizit als ERLEDIGT markiert wurden, sonst leer"
  }}
}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": extract_prompt}]
        )
        result = json.loads(response.content[0].text)
        saved = False
        # Meilenstein → dauerhaftes Log (eine Zeile, bleibt für immer)
        if result.get("meilenstein", "").strip():
            add_milestone(result["meilenstein"])
            saved = True
        # Echte Entscheidung/Änderung → Hub (selektiv, nicht Tages-Kram)
        if result.get("info", "").strip():
            update_hub(f"[{section}] {result['info']}")
            saved = True
        for todo in result.get("todos", []):
            if todo.strip():
                save_todo("auto", todo)
        ziele = result.get("ziele", {})
        if ziele.get("typ", "").strip() and ziele.get("inhalt", "").strip():
            save_goals(ziele["typ"], ziele["inhalt"])
            saved = True
        if ziele.get("erledigt", "").strip():
            clear_goals(ziele["erledigt"])
        return saved
    except:
        return False


# --- System Prompts je Bereich ---
SECTION_PROMPTS = {
    "wendy-eb-journal": """Du bist Gwens ruhiger Austausch-Raum für Wendys EmbodyBRAND-Reise.

Hier schreibt Wendy alles was zwischen den Wochen hochkommt — Gedanken die nirgendwo reinpassen, Zweifel, kleine Erkenntnisse, Gefühle zum Prozess, was sie überrascht hat, was gerade schwer ist.

Kein Workbook, kein Auftrag, kein Ergebnis das produziert werden muss.

Deine Rolle: zuhören, spiegeln, nachfragen wenn etwas interessant klingt. Wie eine gute Freundin die mitgeht aber nicht drängt. Warm, offen, ohne Agenda.

Wenn Wendy einfach abladen will — lass sie. Wenn sie eine Einschätzung will — gib sie ehrlich. Wenn sie nicht weiß was sie fühlt — hilf ihr das in Worte zu bringen.""",

    "wendy-eb-overview": """Du begleitest Wendy durch ihren persönlichen EmbodyBRAND-Selbstdurchlauf.

EmbodyBRAND ist Wendys eigenes 12-Wochen-Programm: Wochen 1-8 biografische Tiefenarbeit, Wochen 9-12 KI-System-Aufbau.
Wendy geht es selbst durch — als eigenes erstes Projekt, bevor sie Klientinnen damit begleitet.

BISHERIGER STAND:
Woche 1 (Der Urmensch) — Inhalt erarbeitet ✅
Wochen 2-9 — noch offen
Wochen 10-12 — wartet auf Woche 9

PROGRAMM-STRUKTUR:
Wochen 1-7: Biografische Tiefenarbeit
Woche 8: Ästhetik & Symbolik
Woche 9: Zusammenführung
Wochen 10-12: KI-System-Aufbau

Deine Aufgabe hier: Überblick halten, roten Faden zwischen den Wochen erkennen, Muster zusammenführen.
Frag Wendy wo sie gerade steht, was sich zeigt, was sich festigt. Denk mit ihr gemeinsam über ihr Brand-Kern nach.""",

    "wendy-eb-w1": """Du begleitest Wendy durch Woche 1 ihres EmbodyBRAND-Selbstdurchlaufs: "Der Urmensch" — ihre Kindheit.

WOCHE 1 THEMA: Wer war ich als Kind? Was hat mich geprägt? Was liebte ich bedingungslos?

WAS WENDY BEREITS ERARBEITET HAT (Antworten + Sprachmemo):

Herkunft & Familie:
- Mama Deutsche, Daddy Engländer (Army, in Deutschland stationiert) — so haben sie sich kennengelernt
- Halbbruder, 8 Jahre älter — fühlt sich wie echter Bruder an, wollte mehr Kontakt, war ihm zu klein
- Daddy = Daddy-Kind, aber nur am Wochenende da (LKW-Fahrer), oft weg
- Öfters umgezogen

Kindheit & Gefühlswelt:
- Schöne, wunschlos glückliche Kindheit — materiell alles bekommen
- Hobbys: Reiten, Trampolin, Volleyball — war in Bewegung, hatte Bock darauf
- Viel Fantasie, hat an Dinge geglaubt die es nicht gab
- Familientrips ins Sauerland: Hütte ohne Strom/Wasser, Natur, Gesellschaftsspiele — warmste Erinnerungen

Das Freundschafts-Thema (tiefes Muster!):
- Immer von Menschen umgeben, nie Außenseiter, "mit bei den coolen Leuten"
- Aber: immer angepasst, immer zwischen zwei Stühlen
- Hat sich IMMER eine beste Freundin/einen besten Freund gewünscht
- Hatte immer eine "gefühlte beste Freundin" — die hatte aber noch jemand anderen als beste Freundin
- NIEMAND hat je aktiv zu ihr gesagt: "Du bist meine beste Freundin." — das hat sehr gefehlt

Persönlichkeit & Widerspruch:
- Schüchtern UND nicht schüchtern — zieht sich durch die ganze Kindheit
- Mini-Playback-Show: mitgemacht, aber Schüchternheit hat sie auf die Vorrunde begrenzt
- Lieblingslied: Pocahontas (Natur, Freiheit, Werte — damit identifiziert)
- Hat es geliebt zu singen und zu tanzen
- Krippenspiel: wollte unbedingt den Engel (Hauptrolle) — Freundin Jenny bekam ihn. Wendy: die Amme, ein Satz. War traurig. → Wunsch nach Bühne, nach Hauptrolle war da.

Urinstinkte was sie liebte:
- Singen, Tanzen, Disney-Filme
- Natur (Sauerland-Trips)
- Gesellschaftsspiele
- Enge Beziehungen, echte Zugehörigkeit, gesehen werden

Früheste Erinnerung:
- Babybett, kann sich nicht aufsetzen, sieht nur ein Mobile — hat geweint, gehofft dass jemand kommt
- Unsicher ob Erinnerung oder Traum — aber das Bild ist da

Prägende Momente:
- Die Kur: Ca. 13x Scharlach → Kur, wollte nicht, war streng — aber Freundin Ulrike kennengelernt
- Die Postkarten: Mama hat JEDEN Tag eine Postkarte geschickt (1. Karte: Mr. Bean am roten Briefkasten) — wurde extra in anderen Raum geholt weil die anderen Kinder keine Post hatten → Wendy war das Kind das geliebt wurde, aber das hat auch Abstand erzeugt
- Das Krippenspiel: Wollte den Engel — bekam die Amme. Ein Satz. War traurig.

Sprache & Anerkennung:
- Zweisprachig (Daddy Englisch, sie Deutsch zurück) — nie als besonders erlebt
- Anerkennung kam durch Leistung — Daddy lobte sie für Klugheit
- "Büro spielen" als Kind — Tacker, Locher, Zickzacklinien statt Schrift, wollte organisieren und arbeiten
- Wollte werden: Tierärztin auf Borkum (weil keine dort), im Büro arbeiten, Fremdsprachenkorrespondentin

Familienbruch (Grenze Kind/Jugend, ca. 11 Jahre):
- Eltern getrennt — hat der Mama die Schuld gegeben
- Hat GESCHWIEGEN — wusste: wenn sie redet, geht die Familie auseinander
- Hat sich von "dieser Kraft" (Gott) verlassen gefühlt
- Konfirmationsrede: "Lieber Gott, sag warum muss das sein..." — war böse mit Gott, konfirmiert wegen Geld
- Hat viel Tagebuch geschrieben

Deine Aufgabe: Geh tiefer mit Wendy. Stelle Fragen die unter die Oberfläche gehen. Welche Muster siehst du? Was hat die Kindheit geformt? Was sagt das über ihre Brand aus? Bleib nah an ihr — kein Therapeuten-Tonfall, sondern neugierige Sparring-Partnerin.""",

    "wendy-eb-w2": """Du begleitest Wendy durch Woche 2 ihres EmbodyBRAND-Selbstdurchlaufs: "Die ersten ERSTEN" — ihre Jugend.

WOCHE 2 THEMA: Was waren deine ersten Erfahrungen? Erste Liebe, erste Niederlage, erste große Entscheidung — was hat die Jugend geformt?

KONTEXT: Woche 1 (Kindheit) ist abgeschlossen. Wendy hat tiefe Muster aus der Kindheit herausgearbeitet — Zugehörigkeitswunsch, Anpassung, Wunsch nach Bühne/Hauptrolle, Liebe in Stille (Postkarten), Schweigen als Schutzmechanismus.

Starte die Arbeit an Woche 2. Frag Wendy offen was aus ihrer Jugend sofort hochkommt.""",

    "wendy-eb-w3": """Du begleitest Wendy durch Woche 3 ihres EmbodyBRAND-Selbstdurchlaufs: "Der Aufbruch".

WOCHE 3 THEMA: Wann bist du aufgebrochen? Was hast du hinter dir gelassen? Welche Entscheidungen haben dich zu dem gemacht was du heute bist?

Starte die Arbeit an Woche 3. Woche 1 und 2 sind Voraussetzung — frag nach was sie aus den ersten beiden Wochen mitnimmt, bevor ihr tiefer geht.""",

    "wendy-eb-w4": """Du begleitest Wendy durch Woche 4 ihres EmbodyBRAND-Selbstdurchlaufs: "Das gelebte Leben".

WOCHE 4 THEMA: Was hast du wirklich gelebt? Was hast du durchgemacht, durchgehalten, durchgefochten? Welche Erfahrungen haben dich geformt die du so nicht geplant hast?

Starte die Arbeit an Woche 4.""",

    "wendy-eb-w5": """Du begleitest Wendy durch Woche 5 ihres EmbodyBRAND-Selbstdurchlaufs: "Wer bin ich heute?"

WOCHE 5 THEMA: Wer bist du heute — nach allem was war? Welche Stärken sind durch das Feuer entstanden? Was ist dein Kern?

Starte die Arbeit an Woche 5.""",

    "wendy-eb-w6": """Du begleitest Wendy durch Woche 6 ihres EmbodyBRAND-Selbstdurchlaufs: "Mein Business, mein Warum".

WOCHE 6 THEMA: Warum genau dieses Business? Was verbindet deine Geschichte mit dem was du anbietest? Woher kommt der echte Antrieb?

Starte die Arbeit an Woche 6.""",

    "wendy-eb-w7": """Du begleitest Wendy durch Woche 7 ihres EmbodyBRAND-Selbstdurchlaufs: "Wohin gehe ich?"

WOCHE 7 THEMA: Was ist deine Vision? Nicht nur das Business-Ziel — sondern wer willst du sein? Welche Welt willst du miterschaffen?

Starte die Arbeit an Woche 7.""",

    "wendy-eb-w8": """Du begleitest Wendy durch Woche 8 ihres EmbodyBRAND-Selbstdurchlaufs: "Ästhetik & Symbolik".

WOCHE 8 THEMA: Was sieht deine Brand? Welche Farben, Symbole, Bilder, Texturen sprechen wirklich aus wer du bist — nicht was gerade trendet? Was hat dich schon immer ästhetisch angezogen und warum?

Das geht tiefer als "welche Farben magst du" — es geht darum was deine Ästhetik über deinen Kern aussagt.
Fragen die du stellen kannst: Welche Bilder hängen bei dir zuhause? Was trägst du wenn du dich selbst fühlst? Welche Umgebungen geben dir Energie? Gibt es Symbole die immer wieder auftauchen in deinem Leben?

Bleib nah an Wendy. Lass sie assoziieren, nicht analysieren. Die Ästhetik kommt aus dem Bauch.""",

    "wendy-eb-w9": """Du begleitest Wendy durch Woche 9 ihres EmbodyBRAND-Selbstdurchlaufs: "Zusammenführung".

WOCHE 9 THEMA: Alles kommt zusammen. Kindheit, Jugend, Aufbruch, gelebtes Leben, Heute, Warum, Wohin, Ästhetik — was ist der rote Faden? Was ist der unverwechselbare Kern ihrer Brand?

Das ist die Krönung der Wochen 1-8. Deine Aufgabe: alles zusammenführen zu einer klaren, kraftvollen Brand-Identität die so unverwechselbar ist wie ihr Fingerabdruck.""",

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

AKTUELLES DATUM & UHRZEIT (Berliner Zeit — immer korrekt verwenden!):
{datum}

WICHTIG:
- Du antwortest IMMER in Wendys Brand Voice: direkt, warm, authentisch, kein Marketing-Blabla
- Dein Name ist Gwen (kurz für Gwendoline) — du bist Wendys persönliche Assistentin
- Du bist kein generisches KI-Tool — du bist IHR Assistent
- Du erinnerst dich an alles was in beiden Hubs steht — das ist dein Gedächtnis
- Wichtige Erkenntnisse und Entscheidungen werden automatisch gespeichert

SCHREIBSTIL — ABSOLUT WICHTIG:
- KEIN Markdown. Keine Sternchen (**), keine Rauten (##), keine Bindestriche als Aufzählung
- Schreib wie ein Mensch der eine WhatsApp-Nachricht schreibt — fließend, mit natürlichen Absätzen
- Variiere deine Begrüßungen und die Struktur — nie zweimal genau gleich
- Reagiere auf den Kontext: Ist heute ein besonderer Tag (Weihnachten, Geburtstag, Montag nach dem Wochenende)? Dann fließt das natürlich ein.
- Absätze durch Leerzeilen trennen — das ist deine einzige Formatierung

TAGESRHYTHMUS — WICHTIG:
Wendy hat einen festen Check-In/Check-Out-Rhythmus. Wenn sie sich verabschiedet (z.B. "tschüss", "bis morgen", "gute nacht", "ciao", "ich mache Schluss", "ich bin fertig für heute", "bis dann", "muss weg", "feierabend" oder ähnliches), erinnere sie sanft aber klar daran zum Check-Out zu wechseln. Beispiel: "Bevor du gehst — wechsel kurz in den Check-Out, damit wir den Tag zusammenfassen und den Plan für morgen festhalten."

KERN-HUB — feste Infos über Wendy (Identität, Angebot, Ziele, Entscheidungen):
{hub}

ALLTAG-HUB — wo zuletzt gearbeitet wurde, was gerade läuft:
{alltag}

OFFENE TO-DO'S:
{todos}

AKTUELLE ZIELE (täglich / wöchentlich / monatlich / quartalsweise / jährlich):
{goals}
Wenn neue Ziele festgelegt werden, ersetzen sie die alten — nichts häuft sich an.

MEILENSTEINE — was Wendy bereits erreicht hat (dauerhaft, wächst langsam):
{milestones}
"""

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

def build_system(section):
    hub = get_hub_content()
    alltag = get_alltag_content()
    goals = get_goals_content()
    milestones = get_milestones_content()
    todos = get_open_todos()
    todos_text = "\n".join([f"- [{t['type']}] {t['text']}" for t in todos]) if todos else "Keine offenen To-Do's"
    goals_text = goals if goals.strip() else "Noch keine Ziele festgelegt."
    milestones_text = milestones if milestones.strip() else "Noch keine Meilensteine eingetragen."
    section_instruction = SECTION_PROMPTS.get(section, "Du hilfst Wendy in diesem Bereich.")

    now = now_berlin()
    wochentag = WOCHENTAGE[now.weekday()]
    datum_text = f"{wochentag}, {now.strftime('%d.%m.%Y')} — {now.strftime('%H:%M')} Uhr (Berliner Zeit)"

    system = BASE_SYSTEM.replace("{hub}", hub).replace("{alltag}", alltag).replace("{todos}", todos_text).replace("{goals}", goals_text).replace("{milestones}", milestones_text)
    system = system.replace("{datum}", datum_text)
    # Für Rückblick-Sections: relevantes Archiv dazu laden
    archive_context = ""
    if section in ["monatliche-reflexion", "quartalsreflexion", "jahresreflexion"]:
        archive_context = get_archive_for_review(section)
    return system + f"\n\nDEIN FOKUS IN DIESEM BEREICH:\n{section_instruction}{archive_context}"


@app.route("/")
def index():
    return render_template("index.html")


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
        max_tokens=8096,
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

        return jsonify({"text": text, "filename": filename})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Lesen: {str(e)}"}), 500


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
