# Open WebUI Knowledge Import

Dieser Ordner ist die **Host-Quelle** für RAG-Wissensdokumente im Projekt `syn4ps3h0me`.

## Mount im Container

Der Ordner wird über `docker-compose.yml` nach:

- `/app/backend/data/knowledge-import`

in den `open-webui`-Container gemountet (read-only).

Damit stehen die Dateien **direkt nach Stack-Start** im Container als Importquelle bereit.

## Nutzung in Open WebUI (RAG)

Gemäß Open-WebUI-RAG-Workflow:

1. Dateien hier ablegen (`.txt`, `.md`, `.pdf`, `.docx`, ...)
2. `docker compose up -d` starten/aktualisieren
3. In Open WebUI: `Workspace -> Knowledge`
4. Dateien aus dem Importbereich in eine Knowledge Base übernehmen/indexieren
5. Knowledge im Chat auswählen, damit Retrieval aktiv ist

## Hinweis zur Wartung

Bitte keine großen statischen Codekopien als Knowledge ablegen, wenn der Code sich häufig ändert.
Besser: strukturierte Architektur-/Dateiübersichten pflegen (z. B. `syn4ps3h0me_rag_knowledge.txt`) und bei Bedarf gezielt auf aktuelle Dateien verweisen.
