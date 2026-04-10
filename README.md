# syn4ps3h0me

## Über dieses Projekt

Dieses Projekt vereinfacht die Installation und Grundkonfiguration einer lokalen Smart-Home-, Monitoring- und Infrastruktur-Umgebung auf dem Raspberry Pi.

Die Installation, Grundkonfiguration und der Start der benötigten Services erfolgen zentral über **`install.sh`**. Abhängig vom Systemzustand kann während des Setups ein **Neustart per `sudo reboot`** erforderlich sein.

Aktuell umfasst das Projekt die automatische Einrichtung und Vorkonfiguration der folgenden Komponenten:

- **Docker**
- **Mosquitto**
- **Telegraf**
- **InfluxDB**
- **Grafana**
- **Pi-hole**
- **Caddy**
- **Open WebUI**

Zusätzlich werden aktuell erste Komponenten für zukünftige KI-/Sprachfunktionen vorbereitet bzw. installiert, darunter:

- **hailo-apps**
- **Whisper-Ressourcen**
- **hailo-ollama**

Damit entsteht eine lokale, selbst gehostete Basis für Monitoring, MQTT-Kommunikation, DNS, HTTPS-Zugriffe und perspektivisch auch für KI-gestützte Erweiterungen.

## Open WebUI: RAG mit lokalem Wissensordner

Für die KI-Antworten in **Open WebUI** gibt es jetzt einen lokalen Wissensordner auf Dateiebene:

- Host-Ordner: `open-webui/knowledge/`
- Container-Pfad: `/app/backend/data/knowledge-import` (read-only gemountet)

So nutzt du ihn:

1. Lege deine Wissensdateien in `open-webui/knowledge/` ab (z. B. `.md`, `.txt`, `.pdf`, `.docx`).
2. Starte/aktualisiere den Stack mit `docker compose up -d`.
3. In Open WebUI: **Workspace → Knowledge** öffnen und die Dateien aus diesem Ordner importieren/hochladen.
4. Beim Chatten dann das entsprechende Knowledge-Objekt auswählen, damit die Antworten auf dieser Wissensbasis laufen (RAG).

**Pi-hole** wird zusätzlich als lokaler DNS-Server und Ad-Blocker vorkonfiguriert. Damit die Namensauflösung im Netzwerk zuverlässig funktioniert, muss **Pi-hole im Router** – z. B. in der **FRITZ!Box** – **korrekt als DNS-Server eingetragen und eingebunden** werden.

**Caddy** wird ebenfalls installiert und vorkonfiguriert, um interne Dienste komfortabel per **HTTPS** bereitzustellen. Dieser Bereich wird aktuell noch weiter ausgebaut.



## Rechtlicher Hinweis

Dies ist ein **inoffizielles Community-Skript** und **kein offizielles Produkt** eines der verwendeten Hersteller oder Softwareanbieter.

Das Repository selbst enthält nur eigene Automatisierungs- und Konfigurationsdateien.  
Benötigte **Drittsoftware** wird über die **offiziellen Bezugsquellen** der jeweiligen Hersteller installiert.

Es gelten immer die jeweiligen **Herstellerlizenzen**, **Nutzungsbedingungen** und **Lizenzmodelle** der eingesetzten Drittsoftware.  
Die Verantwortung für die rechtmäßige Nutzung und Einhaltung dieser Bedingungen liegt beim jeweiligen Nutzer.

## Hinweis zu Empfehlungs- und Affiliate-Links

Dieses Projekt ist ein inoffizielles Community-Projekt.

Einige Links in dieser README können Empfehlungs- oder Affiliate-Links sein. Wenn über solche Links ein Kauf erfolgt, kann eine Provision anfallen. Für dich entstehen dadurch keine zusätzlichen Kosten.

Als Amazon-Partner verdiene ich an qualifizierten Verkäufen.

```bash
 git clone git@github.com:siddy81/syn4ps3h0me.git
```

## Installation auf dem Raspberry Pi (mit `install.sh`)

### Zentrales Admin-Passwort
Das Admin-Passwort für **InfluxDB**, **Grafana** und **Pi-hole** wird zentral über `STACK_ADMIN_PASSWORD` in der .env-Datei gesteuert.
Default ist es auf admin123 gesetzt. Unbedingt vor der Inbetriebnahme ändern!


### Vorbedingungen
Bevor du `install.sh` startest, sollten diese Voraussetzungen erfüllt sein:
- [Raspberry Pi 5 mit mindestens 8 GB Ram, besser 16 GB OS (64-bit, Debian Trixie) mit Internetzugang](https://amzn.to/4dafwWq)
- [Raspberry Pi Ai hat+ 2, 40 tops, hailo 10h accelerator](https://amzn.to/4bsgegf) 
- Der Raspberry Pi AI HAT+ 2 mit 40 TOPS und 8 GB RAM ist derzeit noch nicht erforderlich. 
  Aktuell arbeite ich jedoch an ersten KI-Implementierungen, zum Beispiel im Bereich der Spracherkennung.  
  Dafür wird diese Hardware dann auch notwendig sein.
- Ein Benutzer mit `sudo`-Rechten (Script läuft mit Root/Sudo)
- `systemd` ist aktiv (für den späteren `hailo-ollama.service`)
- GitHub und Hailo-Download-URLs sind aus dem Netzwerk erreichbar
- Projekt liegt lokal auf dem Pi (z. B. in `~/workspace/syn4ps3h0me`)

#### Weitere Hardware
Optional bzw. je nach gewünschtem Ausbau des Setups:

- [45 Watt Netzteil](https://amzn.to/3PwXOTd)
- [Raspberry Pi Gehäuse](https://amzn.to/4uSu5UW)
- [Shelly H&T Gen 3](https://amzn.to/41up2wi)
- [Shelly Motion](https://amzn.to/4bHycuc)
- [Shelly Door/Window](https://amzn.to/40TNPda)
- [shelly 1pm](https://amzn.to/4bHycuc)

### Installation starten
```bash
cd ~/workspace/syn4ps3h0me
chmod +x install.sh
./install.sh
```

### Was `install.sh` auf dem Raspberry Pi installiert und konfiguriert
Das Skript erledigt automatisiert folgende Schritte:

1. **Basis-Pakete via APT**
   - `curl`, `wget`, `git`, `ca-certificates`, `portaudio19-dev`
2. **Docker**
   - installiert Docker (falls noch nicht vorhanden) über `get.docker.com`
   - fügt den Benutzer zur `docker`-Gruppe hinzu
3. **Hailo Apps Umgebung**
   - klont `https://github.com/hailo-ai/hailo-apps.git` nach `~/workspace/hailo-apps` (falls nicht vorhanden)
   - führt dort `sudo ./install.sh` aus
   - lädt `setup_env.sh` und installiert Python GenAI-Abhängigkeiten mit `pip install -e '.[gen-ai]'`
   - lädt Whisper-Ressourcen per `hailo-download-resources --group whisper_chat --arch hailo10h`
4. **Hailo GenAI Model Zoo Paket**
   - lädt `hailo_gen_ai_model_zoo_5.1.1_arm64.deb` herunter
   - installiert das Paket (inkl. Abhängigkeitsauflösung per `apt-get -f install`)
5. **Systemdienst für Hailo Ollama**
   - erstellt/aktualisiert `/etc/systemd/system/hailo-ollama.service`
   - aktiviert und startet den Dienst (`systemctl enable --now` bzw. restart)
   - prüft die lokale API auf `http://localhost:8000/hailo/v1/list`
6. **Projekt-Stack starten**
   - startet am Ende den Docker-Compose-Stack mit `docker compose up -d` (oder Fallback `docker-compose up -d`)

### Nach dem Lauf
- Prüfe den Dienststatus mit `systemctl status hailo-ollama`.
- Prüfe Container mit `docker compose ps`.
- Falls Gruppenrechte neu sind: einmal ab- und wieder anmelden.

### Voice-Pipeline: Wake-Word → Whisper → Router → LLM/Shelly
Die Voice-Pipeline nutzt Wake-Word-Erkennung (Jarvis), transkribiert das Folgekommando lokal über `openai/whisper-base` und routet danach regelbasiert:

- Smart-Home-Kommandos (z. B. „schalte das Licht in der Küche aus“) → Shelly REST
- alle anderen Kommandos → lokales LLM `llama3.2:3b`

Empfohlene `.env`-Einträge:
```env
VOICE_WHISPER_MODE=hf_local
VOICE_WHISPER_MODEL=openai/whisper-base
VOICE_WHISPER_LANGUAGE=de
VOICE_WHISPER_CACHE_DIR=/home/siddy/.cache/huggingface

VOICE_LLM_BASE_URL=http://host.docker.internal:8000
VOICE_LLM_MODEL=llama3.2:3b
VOICE_LLM_TIMEOUT_SECONDS=45

SHELLY_DEVICE_MAP_FILE=/app/app/config/shelly_devices.json
SHELLY_DEVICE_MAP_JSON=
SHELLY_DEFAULT_COMMAND_PATH=/script/light-control
SHELLY_TIMEOUT_SECONDS=5

VOICE_TTS_SHELL_COMMAND=
```

### Shelly-Script bereitstellen

Für das Routing auf mehrere Shellys wird eine Lookup-Tabelle verwendet (Raum/Alternative Bezeichnungen/Gruppe → DNS/IP).
Beispiel: `voice-pipeline/app/config/shelly_devices.example.json`.

Das wiederverwendbare Shelly-Script liegt in `shelly_script/shelly_1pm_control.js`.

Kurzablauf:
1. Shelly Web UI öffnen → **Scripts**
2. Neues Script anlegen, Inhalt aus Datei einfügen (gleiches Script auf jedem Ziel-Shelly)
3. Script starten
4. Für jeden Shelly einen eindeutigen DNS-/IP-Eintrag in die Lookup-Tabelle setzen
5. Testen mit: `http://<SHELLY-IP>/script/light-control?action=off`

Antwort ist JSON mit `ok=true|false` und `message`, was von der Python-Pipeline ausgewertet wird.

## 1. Architekturüberblick

### Was macht Pi-hole?
Pi-hole stellt den zentralen DNS-Resolver im Heimnetz bereit. Über statische DNS-Einträge werden Geräte- und Service-Namen zuverlässig intern aufgelöst.

### Was machen die Docker-Services?
- Mosquitto: MQTT-Broker z.B. für Shelly-Geräte oder andere Geräte die MQTT fähig sind
- Telegraf: Liest MQTT-Nachrichten und schreibt sie nach InfluxDB.
- InfluxDB: Datenbank - speichert die geloggten Daten (z.B. MQTT-Daten) 
- Grafana: Dashboards und Visualisierung.
- Pi-hole: DNS-WebUI und lokaler DNS-Server.
- Caddy: Reverse Proxy für HTTPS/TLS (lokale Zertifikate im Heimnetz).

### Wichtiger MQTT-Hinweis für Shelly H&T Geräte
Für **Shelly H&T (HT) Geräte** muss der MQTT-Topic-/Gerätename zwingend mit dem Präfix **`shelly_ht_`** beginnen.
Nur so werden die Daten in den vorhandenen Telegraf/Influx/Grafana-Flows korrekt erkannt und in den HT-Dashboards sauber angezeigt.

### Warum `arkham.asylum` intern?
- Einheitliches, merkbares Namensschema für Geräte und Services.
- Entkopplung von wechselnden IP-Adressen in Clients/Skripten.
- Klare Trennung zwischen internem Intranet-DNS und öffentlicher DNS-Welt.

## 2. DNS-Namenskonzept

### Geräte-Mapping
- `<PC_NAME>.arkham.asylum` → `192.168.1.3` (PC)


### Service-FQDN-Mapping (zeigen auf Raspberry Pi )
- `pihole.arkham.asylum`

Die statischen DNS-Einträge liegen in `docker/pihole/custom.list`.

## 3. Setup Schritt-für-Schritt

### Voraussetzungen
- Docker + Docker Compose Plugin (`docker compose`)
- Raspberry Pi Host unter z.B. `192.168.1.101`
- Zugriff auf Router/DHCP-Konfiguration

## Docker installieren in Shell

```bash
curl -fsSL https://get.Docker.com -o get-Docker.sh
sudo sh get-Docker.sh
sudo usermod -aG docker $USER
newgrp docker
```

## Alle Docker instanzen beenden und alle Daten löschen 

```bash
# (Vorsicht) löscht einfach alles! Alle Daten aller Docker-Container  
docker rm -f $(docker ps -aq) && docker volume rm $(docker volume ls -q) && docker system prune -a --volumes -f 

docker compose down -v --remove-orphans

docker network prune -f

#Ein-Befehl-Variante (Container + Volumes + Netzwerke, ohne Images zu löschen)
docker system prune --volumes -f

docker system prune -a --volumes -f


# falls pihole herumzickt:
docker compose stop pihole
docker compose rm -f pihole

sudo rm -rf /home/siddy/syn4ps3h0me/docker/pihole/etc-pihole
sudo rm -rf /home/siddy/syn4ps3h0me/docker/pihole/etc-dnsmasq.d

mkdir -p /home/siddy/syn4ps3h0me/docker/pihole/etc-pihole
mkdir -p /home/siddy/syn4ps3h0me/docker/pihole/etc-dnsmasq.d

docker compose up -d --force-recreate pihole
```

### Konfiguration vorbereiten
```bash
cp .env .env.local  # optional backup before editing
```

### Zentrales Admin-Passwort
Das Admin-Passwort für **InfluxDB**, **Grafana** und **Pi-hole** wird zentral über `STACK_ADMIN_PASSWORD` gesteuert.
Default ist es auf admin123 gesetzt. Unbedingt vor der Inbetriebnahme ändern! 

Optional kannst du einzelne Services weiterhin separat überschreiben:
- `INFLUXDB_PASSWORD`
- `GF_ADMIN_PASSWORD`
- `PIHOLE_WEBPASSWORD`


Standardwerte stehen direkt in `.env` (produktiv genutzt):
- `INTRANET_DOMAIN=arkham.asylum`
- `TZ=Europe/Berlin`
- `STACK_ADMIN_PASSWORD=admin123`

### Start / Stop
```bash
# Stack starten
docker compose up -d

# Stack stoppen
docker compose down
```

### HTTP/HTTPS
Erreichbar sind die Services mit der default-Einstellung über die DNS-Einträge: 
-  
   → `grafana` `http://nightmaresiddious.arkham.asylum:3000`  
   → `pihole` `http://nightmaresiddious.arkham.asylum:8088`  
   → `mosquitto` `http://nightmaresiddious.arkham.asylum:1883`  



Caddy nutzt standardmäßig eine interne lokale CA (`tls internal`). Dadurch funktionieren HTTPS-Zugriffe im Heimnetz auch ohne öffentliche Domain/Portfreigaben.
Die Proxy-/TLS-Konfiguration liegt in `caddy/config.json` (Caddy JSON Config).
Die wichtigsten Variablen in `.env`:
- `GRAFANA_DOMAIN=grafana.deine-domain.tld`
- `PIHOLE_DOMAIN=pihole.deine-domain.tld`
- `LEGACY_HOST_DOMAIN=nightmaresiddious.arkham.asylum` (optional, damit Zugriff über den Hostnamen ebenfalls per HTTPS funktioniert)
- `LEGACY_HOST_IP=192.168.1.101` (optional, damit Zugriff über die Host-IP per HTTPS ebenfalls funktioniert)

Wichtig:
- Beim ersten Aufruf meldet der Browser ein nicht vertrauenswürdiges Zertifikat (interne CA). Das ist im LAN erwartbar.
- Für saubere Warnungsfreiheit musst du die Caddy-Root-CA auf Clients importieren.
- Falls du später echte öffentliche Domains nutzt, kannst du wieder auf Let's Encrypt umstellen.


Wenn du von einer älteren Caddy-Konfiguration kommst und der Container weiterhin mit alten Fehlern startet, entferne einmalig alte persistierte Caddy-Config:
```bash
docker compose down
docker volume rm shelly-stack_caddy_config 2>/dev/null || true
docker compose up -d --force-recreate caddy
```


Zusätzlich sind als Fallback die direkten Service-Ports wieder aktiv:
- Grafana direkt: `http://nightmaresiddious.arkham.asylum:3000` bzw. `http://192.168.1.101:3000`
- Pi-hole direkt: `http://nightmaresiddious.arkham.asylum:8088/admin/` bzw. `http://192.168.1.101:8088/admin/`

Wichtig: Diese direkten Ports sprechen **HTTP**, nicht HTTPS.
`https://...:3000` oder `https://...:8088` führt zu Browser-Fehlern.

### Erster Login Pi-hole
1. Pi-hole öffnen: `https://pihole.arkham.asylum/admin/` (bereitgestellt über Caddy Reverse Proxy).
   Alternativ (Legacy-Host): `https://nightmaresiddious.arkham.asylum/admin/`.
2. Mit dem zentralen Passwort `STACK_ADMIN_PASSWORD` aus der produktiven `.env` anmelden (optional pro Service mit eigenen Variablen überschreibbar).
3. Optionales Theme wird über `PIHOLE_WEBTHEME` gesteuert (Default: `default-darker` = „Pi-hole Midnight“).
4. DNS-Upstream-Resolver werden über `PIHOLE_DNS_UPSTREAMS` gesetzt (Default: `1.1.1.1;1.0.0.1;1.1.1.1;9.9.9.9`).
5. Unter *Local DNS* prüfen, ob die Einträge aus `custom.list` aktiv sind.

### Router / DHCP auf Pi-hole-DNS umstellen
- Im Router als primären DNS-Server `192.168.1.101` setzen.
- DHCP-Leases erneuern (oder Clients neu verbinden), damit Clients Pi-hole als DNS verwenden.

### Feste IP-Adressen per Pi-hole DHCP vergeben (optional)
Wenn Pi-hole auch DHCP übernehmen soll (z. B. für feste IP-Zuweisungen), gehe so vor:

1. **Router-DHCP deaktivieren** (wichtig: nur ein DHCP-Server im Netz).
2. In `.env` folgende Variablen setzen:
   - `PIHOLE_DHCP_ACTIVE=true`
   - `PIHOLE_DHCP_START=192.168.1.150`
   - `PIHOLE_DHCP_END=192.168.1.220`
   - `PIHOLE_DHCP_ROUTER=192.168.1.1`
   - `PIHOLE_DHCP_LEASETIME=24h`
3. Statische Leases in `docker/pihole/etc-dnsmasq.d/04-static-dhcp.conf` eintragen:

```ini
# Beispiel (MACs anpassen)
dhcp-host=AA:BB:CC:DD:EE:01,192.168.1.3,darksiddious,infinite
dhcp-host=AA:BB:CC:DD:EE:02,192.168.1.101,nightmaresiddious,infinite
```

4. Pi-hole neu starten:
```bash
docker compose up -d --force-recreate pihole
```

Hinweis: Das Vorgehen entspricht der empfohlenen Pi-hole-Rolle als zentraler DNS/DHCP-Dienst im LAN.

## 4. Betriebsdoku

### Pi-hole Docker-Konfiguration (laut offizieller Docker-Variablen)
Die Pi-hole-Konfiguration nutzt primär `FTLCONF_*` Variablen:
- Passwort: `FTLCONF_webserver_api_password` (aus `.env`: `STACK_ADMIN_PASSWORD`, optional via `PIHOLE_WEBPASSWORD` überschreibbar)
- Theme: `FTLCONF_webserver_interface_theme` (aus `.env`: `PIHOLE_WEBTHEME`)
- DNS-Upstream: `FTLCONF_dns_upstreams` (aus `.env`: `PIHOLE_DNS_UPSTREAMS`)
- DNSSEC: `FTLCONF_dns_dnssec` (aus `.env`: `PIHOLE_DNSSEC=true`)
- Listening Mode: `FTLCONF_dns_listeningMode=all`

Nach Änderungen anwenden:
```bash
docker compose up -d --force-recreate pihole
```

Hinweis: Bei bestehendem persistenten Volume kann ein altes Passwort aktiv bleiben. Dann explizit setzen:
```bash
docker compose exec pihole pihole setpassword "$STACK_ADMIN_PASSWORD"
```

### Blocklisten für Werbung und gefährliche Domains
Der Stack liefert eine benutzerdefinierte Liste unter `docker/pihole/adlists.list` (u. a. StevenBlack, RPiList, Firebog, anudeepND).

Blocklisten anwenden/aktualisieren:
```bash
docker compose exec pihole pihole -g
```

Hinweis: `docker/pihole/adlists.list` muss LF-Zeilenenden haben (kein CRLF), sonst erscheinen beim Gravity-Update `Invalid Target ...^M`-Fehler.

Optional prüfen:
```bash
docker compose exec pihole pihole -q doubleclick.net
docker compose exec pihole pihole -q phishing
```

### Neustartverhalten
Alle Services laufen mit `restart: unless-stopped` und starten nach Host-Reboot automatisch erneut.

### Logs prüfen
```bash
# Gesamte Logs
docker compose logs -f

# Pi-hole Logs
docker compose logs -f pihole
```

### Update-Prozess
```bash
# Images aktualisieren
docker compose pull

# Container mit neuem Image neu erstellen
docker compose up -d

# Verwaiste alte Images aufräumen (optional)
docker image prune -f
```

## 5. Smoke Tests (copy/paste)

```bash
# Compose-Datei validieren
docker compose config

# Stack starten
docker compose up -d

# DNS-Auflösung über Pi-hole prüfen (expliziter DNS-Server)
nslookup grafana.arkham.asylum 192.168.1.101
nslookup mqtt.arkham.asylum 192.168.1.101
nslookup darksiddious.arkham.asylum 192.168.1.101

# Erreichbarkeit prüfen
ping -c 2 nightmaresiddious.arkham.asylum
curl -I https://grafana.arkham.asylum
curl -I https://pihole.arkham.asylum/admin/
```

## 6. Troubleshooting

### Pi-hole Theme auf "Pi-hole Midnight" setzen
Ja. Das Theme kann zentral per Env-Variable gesetzt werden und erscheint dann in den Web Interface/API Settings:
- `.env`: `PIHOLE_WEBTHEME=default-darker`

Übernahme:
```bash
docker compose up -d --force-recreate pihole
```

### Verbindung abgelehnt oder TLS-Fehler
Symptom: Browser zeigt `ERR_CONNECTION_REFUSED` oder TLS-Fehler auf den alten Port-URLs.

Hintergrund:
- Mit Caddy laufen die abgesicherten Zugriffe standardmäßig über **Port 443**.
- Die direkten Ports (`3000`, `8088`) sind als HTTP-Fallback verfügbar; HTTPS läuft aber über Port 443 via Caddy.

Nutze stattdessen:
```bash
# HTTPS via Caddy
https://grafana.arkham.asylum
https://pihole.arkham.asylum/admin/
https://nightmaresiddious.arkham.asylum/login
https://nightmaresiddious.arkham.asylum/admin/
https://192.168.1.101/login
https://192.168.1.101/admin/

# HTTP-Fallback direkt auf Service-Ports
http://192.168.1.101:3000
http://192.168.1.101:8088/admin/
```

### 403 auf Pi-hole WebUI (Root URL)
Symptom: `https://pihole.arkham.asylum` zeigt `403 Access denied`.

Hintergrund:
- Pi-hole liefert auf `/` je nach Version/Config keinen Dashboard-Inhalt aus.
- Der Stack enthält deshalb einen Redirect von `/` auf `/admin/`.

Prüfung:
```bash
curl -I https://pihole.arkham.asylum
curl -I https://pihole.arkham.asylum/admin/
```

Lösung:
- Sicherstellen, dass `docker/pihole/lighttpd-external.conf` gemountet ist.
- Pi-hole neu erstellen:
```bash
docker compose up -d --force-recreate pihole
```

### Gravity-Update zeigt `Invalid Target ...^M`
Symptom: `pihole -g` meldet für jede Liste `Invalid Target` und zeigt `^M` am Ende der URL.

Ursache:
- Windows-CRLF (`\r\n`) in `docker/pihole/adlists.list`.

Prüfung:
```bash
cat -vet docker/pihole/adlists.list
```
Wenn am Zeilenende `^M$` erscheint, enthält die Datei CRLF.

Lösung:
```bash
# Auf dem Host auf LF normalisieren
sed -i 's/\r$//' docker/pihole/adlists.list

# Pi-hole neu laden und Gravity neu aufbauen
docker compose restart pihole
docker compose exec pihole pihole -g
```

Zusätzlich erzwingt `.gitattributes` im Repo LF für Pi-hole-Listen/Configs.

### DHCP verteilt keine festen IPs
Symptom: Gerät bekommt trotz `dhcp-host`-Eintrag keine gewünschte IP.

Prüfung:
```bash
docker compose exec pihole pihole-FTL --config dhcp.active
docker compose exec pihole grep -n "^dhcp-host" /etc/dnsmasq.d/04-static-dhcp.conf
```

Lösung:
- Prüfen, dass Router-DHCP wirklich deaktiviert ist.
- MAC-Adresse im `dhcp-host`-Eintrag exakt übernehmen.
- DHCP-Lease am Client erneuern oder Gerät neu verbinden.

### Port 53 belegt
Symptom: Pi-hole startet nicht, Fehler zu `53/tcp` oder `53/udp`.

Prüfung:
```bash
sudo ss -lntup | rg ':53'
```

Lösung:
- Lokalen DNS-Resolver auf dem Host deaktivieren/umkonfigurieren (z. B. `systemd-resolved`).
- Danach Stack neu starten: `docker compose up -d pihole`.

### DNS-Cache Problem
Symptom: Alter DNS-Eintrag trotz Änderung.

Lösung:
- Pi-hole Cache leeren (WebUI oder `pihole restartdns` im Container).
- Client-DNS-Cache leeren (OS abhängig).
- DHCP-Lease am Client erneuern.

### Falsche DNS-Antworten
Symptom: FQDN zeigt auf falsche IP.

Prüfung:
```bash
cat docker/pihole/custom.list
nslookup telegraf.arkham.asylum 192.168.1.101
```

Lösung:
- `custom.list` korrigieren.
- Pi-hole DNS neu laden:
```bash
docker compose exec pihole pihole restartdns
```

---

## Compose-Design (Refactor-Notizen)
- Konsistente `container_name` in lowercase-kebab-case.
- `hostname` pro Service gesetzt.
- Gemeinsames Docker-Netzwerk `intranet` für alle Services.
- Pi-hole persistent über:
  - `docker/pihole/etc-pihole`
  - `docker/pihole/etc-dnsmasq.d`
  - `docker/pihole/custom.list`
  - `docker/pihole/adlists.list`

Details zu Änderungen und Ports stehen in `CHANGELOG.md`.

## Grafana

### Anpassung der Stromkosten

Damit die Kosten im Dashboard korrekt dargestellt werden, 
müsst ihr in der Datei `shelly-overview.json` im Bereich 
**Gesamtkosten** den Standardwert `0.3577` durch euren eigenen Strompreis ersetzen.
