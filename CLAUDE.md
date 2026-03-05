# Business-Assistent Workspace — Wendy Whitfield

Dieser Workspace enthält Wendys persönlichen Business-Assistenten.
Eine Flask-Web-App mit Anthropic API, live auf Railway deployed.

**Live-URL:** https://web-production-afd9f.up.railway.app
**Lokal starten:** `python app.py` → http://localhost:5000

---

## Was dieser Workspace ist

Kein Alltags-Arbeitsplatz — sondern die technische Werkstatt.
Hier werden neue Features gebaut, Bugs gefixt, der Hub befüllt.
Der Alltag läuft direkt in der App unter der Live-URL.

---

## Wichtigste Dateien

| Datei | Zweck |
|---|---|
| `app.py` | Flask-Backend, alle API-Endpoints, System-Prompts |
| `data/hub.md` | Das Gedächtnis der App — Wendys Business-Kern |
| `templates/index.html` | HTML-Struktur der App |
| `static/style.css` | Design (Orange #fca73d, Braun #9B6520, Gelb #ffd500) |
| `static/script.js` | Frontend-Logik (Chat, Voice, Mobile-Menü) |
| `requirements.txt` | Python-Dependencies |
| `Procfile` | Railway-Deployment |

---

## Technischer Stack

- **Backend:** Flask (Python) + Anthropic API (claude-sonnet-4-6)
- **Datenbank:** SQLite (data/assistant.db) — Chat-History + To-Dos
- **Deployment:** Railway (GitHub auto-deploy bei Push)
- **Voice:** Web Speech API (WhatsApp-Style: halten → aufnehmen → loslassen = senden)
- **Mobile:** PWA-ready, responsive, installierbar auf iOS & Android

---

## Deployment

Jeder `git push` → Railway deployed automatisch (1-2 Minuten).
ANTHROPIC_API_KEY ist als Railway-Variable gesetzt.

---

## Commands

| Command | Wann nutzen |
|---|---|
| `/prime` | Session starten — aktuellen Stand laden |
| `/shutdown` | Session beenden |

---

## Kritische Anweisung

- Hub (`data/hub.md`) enthält den vollständigen Business-Kontext — vor Änderungen lesen
- Brand-Farben NICHT ändern ohne Rückfrage: Orange #fca73d, Braun #9B6520
- Nach Code-Änderungen immer: `python -c "from app import app; print('OK')"` testen
- Dann committen und pushen → Railway deployt automatisch
