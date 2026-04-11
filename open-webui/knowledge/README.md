# Open WebUI Knowledge Import

Lege hier Dateien ab, die du in Open WebUI als Knowledge-Quellen verwenden willst.

## Out-of-the-box Import

Der Compose-Stack enthält einen Bootstrap-Service `open-webui-knowledge-bootstrap`, der Dateien automatisch in Open WebUI importiert:

- User-Content aus diesem Ordner (`open-webui/knowledge/`) -> Knowledge Collection `user-content`
- Live-Projektquellcode aus dem Repo-Root -> Knowledge Collection `syn4ps3h0me-live`

Bootstrap manuell starten/neu ausführen:

```bash
docker compose up -d open-webui
docker compose run --rm open-webui-knowledge-bootstrap
```

Optional automatisch nach jedem Stack-Start ausführen:

```bash
docker compose up -d open-webui open-webui-knowledge-bootstrap
```


### Offizielle Doku-Hinweis
Laut Open WebUI RAG-Dokumentation müssen lokale Dateien in Workspace/Documents/Knowledge hochgeladen werden.
Dieser Bootstrap-Service automatisiert genau diesen Upload-Prozess per API für `user-content` und `syn4ps3h0me-live`.
