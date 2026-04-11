# Open WebUI Knowledge Import

Dieser Ordner ist die **Host-Quelle** für RAG-Wissensdokumente im Projekt `syn4ps3h0me`.

## Mount im Container

Der Ordner wird über `docker-compose.yml` nach:

- `/app/backend/data/knowledge-import` (für Open WebUI)
- `/knowledge-import` (für den Auto-Sync-Service)

gemountet.

## Automatisches Einlesen (RAG, out of the box)

Zusätzlich läuft der Service `open-webui-knowledge-sync`, der Dateien und Unterordner **rekursiv** aus diesem Ordner automatisch per Open-WebUI-API in eine Knowledge Base synchronisiert.

Standardziel:
- Knowledge Base Name: `syn4ps3h0me`

Damit ist das Wissen nach Stack-Start ohne manuelle UI-Importschritte in Open WebUI als Knowledge verfügbar.

## Unterordner / rekursive Struktur

Der Sync verarbeitet die komplette Ordnerstruktur rekursiv (z. B. `rezepte/familie/*.md`, `buecher/wissen/**/*.pdf`).
Dateien werden über ihren relativen Pfad getrackt, damit gleichnamige Dateien in unterschiedlichen Unterordnern korrekt behandelt werden.

## Unterstützte Dateitypen (Standard)

`txt, md, pdf, docx, doc, rtf, csv, json`

(änderbar über `KNOWLEDGE_SYNC_EXTENSIONS` in der `.env`)

## Wichtige ENV-Variablen

- `OPEN_WEBUI_BASE_URL` (Default: `http://127.0.0.1:8080`)
- `OPEN_WEBUI_ADMIN_EMAIL`
- `OPEN_WEBUI_ADMIN_PASSWORD`
- `OPEN_WEBUI_KNOWLEDGE_NAME` (Default: `syn4ps3h0me`)
- `KNOWLEDGE_SYNC_INTERVAL_SECONDS` (Default: `120`)

## Hinweis zur Wartung

Bitte keine großen statischen Codekopien als Knowledge ablegen, wenn der Code sich häufig ändert.
Besser: strukturierte Architektur-/Dateiübersichten pflegen (z. B. `syn4ps3h0me_rag_knowledge.txt`) und bei Bedarf gezielt auf aktuelle Dateien verweisen.
