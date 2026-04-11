# Open WebUI Knowledge Import

Dieser Ordner ist die **Host-Quelle** für RAG-Wissensdokumente im Projekt `syn4ps3h0me`.

## Mount im Container

Der Ordner wird über `docker-compose.yml` nach:

- `/app/backend/data/knowledge-import` (für Open WebUI)
- `/knowledge-import` (für den Auto-Sync-Service)

gemountet.

## Automatisches Einlesen (RAG, out of the box)

Der Service `open-webui-knowledge-sync` synchronisiert Inhalte automatisch per Open-WebUI-API.

### Kategorien (Knowledge Collections)

- **Jeder Top-Level-Ordner** unter `open-webui/knowledge/` wird als **eigene Knowledge-Kategorie** behandelt.
  - Beispiel: `Rezepte/` -> Knowledge-Kategorie `Rezepte`
- **Dateien im Root** von `open-webui/knowledge/` landen in einer separaten Root-Kategorie.
  - Standardname: `syn4ps3h0me` (anpassbar)

### Keine Redundanz / Updates statt Duplikate

- Dateien werden per SHA256 verglichen.
- Bei Änderungen wird die alte Datei-Verknüpfung entfernt und durch die neue ersetzt.
- Gelöschte lokale Dateien werden auch aus Open WebUI entfernt.
- Gleichnamige Dateien in verschiedenen Unterordnern sind möglich (Tracking über relativen Pfad).

## Unterordner / rekursive Struktur

Der Sync verarbeitet die komplette Ordnerstruktur rekursiv (z. B. `rezepte/familie/*.md`, `buecher/wissen/**/*.pdf`).

## Unterstützte Dateitypen (Standard)

`txt, md, pdf, docx, doc, rtf, csv, json`

(änderbar über `KNOWLEDGE_SYNC_EXTENSIONS` in der `.env`)

## Wichtige ENV-Variablen

- `OPEN_WEBUI_BASE_URL` (Default: `http://127.0.0.1:8080`)
- `OPEN_WEBUI_ADMIN_EMAIL`
- `OPEN_WEBUI_ADMIN_PASSWORD`
- `OPEN_WEBUI_ROOT_KNOWLEDGE_NAME` (Default: `syn4ps3h0me`) – Kategorie für Root-Dateien
- `OPEN_WEBUI_KNOWLEDGE_PREFIX` (Default: leer) – optionales Prefix für Ordner-Kategorien
- `KNOWLEDGE_SYNC_INTERVAL_SECONDS` (Default: `120`)

## Hinweis zur Wartung

Bitte keine großen statischen Codekopien als Knowledge ablegen, wenn der Code sich häufig ändert.
Besser: strukturierte Architektur-/Dateiübersichten pflegen (z. B. `syn4ps3h0me_rag_knowledge.txt`) und bei Bedarf gezielt auf aktuelle Dateien verweisen.
