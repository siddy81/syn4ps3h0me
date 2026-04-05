# Open WebUI Knowledge Import

Lege hier Dateien ab, die du in Open WebUI als Knowledge-Quellen verwenden willst.

Beispiele:
- Betriebsanleitungen
- Notizen/Runbooks
- Markdown-Dokumentation
- FAQ-Dateien

## Automatischer Ingest

Der Compose-Stack enthält einen separaten Service `open-webui-knowledge-ingest`, der:

1. sich über die Open-WebUI-API anmeldet,
2. eine definierte Knowledge Base erstellt (falls noch nicht vorhanden),
3. neue oder geänderte Dateien aus diesem Ordner hochlädt und zuordnet,
4. gelöschte Dateien aus dem Open-WebUI-Dateispeicher entfernt.

Standardmäßig wird die Knowledge Base `knowledge-import` verwendet.
Das Intervall kann über `OPEN_WEBUI_INGEST_INTERVAL_SECONDS` in `.env` gesteuert werden.
