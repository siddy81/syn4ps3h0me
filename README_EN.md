# syn4ps3h0me

## About this project

This project simplifies the installation and baseline configuration of a local smart home, monitoring, and infrastructure environment on a Raspberry Pi.

Installation, baseline configuration, and startup of required services are handled centrally via **`install.sh`**. Depending on the system state, a **reboot via `sudo reboot`** may be required during setup.

At the moment, the project includes automated setup and pre-configuration of the following components:

- **Docker**
- **Mosquitto**
- **Telegraf**
- **InfluxDB**
- **Grafana**
- **Pi-hole**
- **Caddy**
- **Open WebUI**

In addition, initial components for future AI/voice features are currently prepared or installed, including:

- **hailo-apps**
- **Whisper resources**
- **hailo-ollama**

This creates a local, self-hosted foundation for monitoring, MQTT communication, DNS, HTTPS access, and AI-assisted extensions.

A **voice pipeline** for local voice control has also been newly implemented:

- The system waits for a **freely configurable wake word/keyword**.
- After the wake word, you can speak directly with the **local AI**; the response is played through the **current speakers**.
- For smart-home commands such as “**Turn the living room light on/off**”, the configured **Shelly** device is triggered.
- Requirement for Shelly control: the script **`shelly_1pm_control.js`** must be running on the target device.

- Shelly device mapping (e.g. `livingroomlight`) is configured via **`voice-pipeline/app/config/shelly_devices.json`**.
  Example entry:
  ```json
  {
    "id": "livingroom_light",
    "room": "livingroom",
    "aliases": ["livingroom", "livingroomlight"],
    "base_url": "http://livingroom-light.arkham.asylum",
    "command_path": "/script/light-control"
  }
  ```

## Open WebUI: RAG with a local knowledge folder

For AI responses in **Open WebUI**, there is now a local knowledge folder at file level:

- Host folder: `open-webui/knowledge/`
- Container path: `/app/backend/data/knowledge-import` (mounted read-only)

How to use it:

1. Place your knowledge files in `open-webui/knowledge/` (e.g. `.md`, `.txt`, `.pdf`, `.docx`).
2. Start/update the stack with `docker compose up -d`.
3. In Open WebUI: open **Workspace → Knowledge** and import/upload files from this folder.
4. When chatting, select the corresponding knowledge object so responses use this knowledge base (RAG).

**Pi-hole** is also pre-configured as a local DNS server and ad blocker. To ensure reliable name resolution in your network, **Pi-hole must be correctly configured and integrated as DNS server in your router** (e.g. a **FRITZ!Box**).

**Caddy** is also installed and pre-configured to provide internal services conveniently via **HTTPS**. This area is still being expanded.

## Legal notice

This is an **unofficial community script** and **not an official product** of any of the manufacturers or software providers used.

The repository itself only contains its own automation and configuration files.  
Required **third-party software** is installed from the respective manufacturers’ **official sources**.

The applicable **vendor licenses**, **terms of use**, and **licensing models** of the third-party software always apply.  
Each user is responsible for lawful use and compliance with these terms.

## Note on referral and affiliate links

This project is an unofficial community project.

Some links in this README may be referral or affiliate links. If a purchase is made through such links, a commission may be paid. There is no extra cost for you.

As an Amazon Associate, I earn from qualifying purchases.

```bash
 git clone git@github.com:siddy81/syn4ps3h0me.git
```

## Installation on Raspberry Pi (with `install.sh`)

### Passwords / Secrets (`.env`)
Installation uses **service-specific secrets** in `.env` (no shared mandatory password for all services).
Set/change these before production use:

- `MQTT_PASSWORD`
- `INFLUXDB_PASSWORD`
- `INFLUXDB_WRITE_TOKEN`
- `GRAFANA_ADMIN_PASSWORD`
- `PIHOLE_API_PASSWORD`
- `PIHOLE_ADMIN_PASSWORD`
- `OPEN_WEBUI_ADMIN_PASSWORD`

Note: Some older README/setup states mention `STACK_ADMIN_PASSWORD`. For the current Compose stack, the individual variables above are authoritative.

### Prerequisites
Before starting `install.sh`, the following requirements should be met:
- [Raspberry Pi 5 with at least 8 GB RAM, preferably 16 GB, OS (64-bit, Debian Trixie) with internet access](https://amzn.to/4dafwWq)
- [Raspberry Pi AI HAT+ 2, 40 TOPS, Hailo 10H accelerator](https://amzn.to/4bsgegf)
- The Raspberry Pi AI HAT+ 2 with 40 TOPS and 8 GB RAM is not strictly required yet.
  However, I am currently working on initial AI implementations, e.g. in speech recognition.
  This hardware will become necessary for that.
- A user with `sudo` permissions (script runs with Root/Sudo)
- `systemd` active (for later `hailo-ollama.service`)
- GitHub and Hailo download URLs reachable from the network
- Project cloned locally on the Pi (e.g. `~/workspace/syn4ps3h0me`)

#### Additional hardware
Optional, depending on how far you want to expand the setup:

- [45 watt power supply](https://amzn.to/3PwXOTd)
- [Raspberry Pi case](https://amzn.to/4uSu5UW)
- [Shelly H&T Gen 3](https://amzn.to/41up2wi)
- [Shelly Motion](https://amzn.to/4bHycuc)
- [Shelly Door/Window](https://amzn.to/40TNPda)
- [Shelly 1PM](https://amzn.to/4bHycuc)

### Start installation
```bash
cd ~/workspace/syn4ps3h0me
chmod +x install.sh
./install.sh
```

### What `install.sh` installs and configures on Raspberry Pi
The script automates these steps:

1. **Base packages via APT**
   - `curl`, `wget`, `git`, `ca-certificates`, `portaudio19-dev`
2. **Docker**
   - installs Docker (if not yet present) via `get.docker.com`
   - adds the user to the `docker` group
3. **Hailo Apps environment**
   - clones `https://github.com/hailo-ai/hailo-apps.git` into `~/workspace/hailo-apps` (if missing)
   - runs `sudo ./install.sh` there
   - sources `setup_env.sh` and installs Python GenAI dependencies with `pip install -e '.[gen-ai]'`
   - downloads Whisper resources via `hailo-download-resources --group whisper_chat --arch hailo10h`
4. **Hailo GenAI Model Zoo package**
   - downloads `hailo_gen_ai_model_zoo_5.1.1_arm64.deb`
   - installs package (including dependency resolution via `apt-get -f install`)
5. **System service for Hailo Ollama**
   - creates/updates `/etc/systemd/system/hailo-ollama.service`
   - enables and starts service (`systemctl enable --now` or restart)
   - checks local API at `http://localhost:8000/hailo/v1/list`
6. **Start project stack**
   - finally starts Docker Compose stack with `docker compose up -d` (or fallback `docker-compose up -d`)

### After running
- Check service status with `systemctl status hailo-ollama`.
- Check containers with `docker compose ps`.
- If group permissions are new: log out and back in once.

### Voice pipeline: Wake word → Whisper → Router → LLM/Shelly
The voice pipeline uses wake-word detection (Nova), transcribes the following command locally via `openai/whisper-base`, then routes based on rules:

- Smart-home commands (e.g. “turn off the kitchen light”) → Shelly REST
- all other commands → local LLM `llama3.2:3b`

Recommended `.env` entries:
```env
# Container User/Audio Runtime
VOICE_HOST_UID=1000
VOICE_HOST_GID=1000

# Wake word
VOICE_WAKEWORD_MODEL=Nova
VOICE_WAKEWORD_MODEL_PATH=
VOICE_WAKE_WORD_THRESHOLD=0.5
VOICE_WAKE_EVENT_COOLDOWN_SECONDS=2.0
VOICE_POST_WAKE_RECORD_SECONDS=6
VOICE_POST_WAKE_MIN_RECORD_SECONDS=0.45
VOICE_POST_WAKE_SILENCE_SECONDS=0.35
VOICE_POST_WAKE_SILENCE_RMS_THRESHOLD=550

# Audio/Devices
VOICE_AUDIO_SAMPLE_RATE=16000
VOICE_AUDIO_DEVICE_REFRESH_SECONDS=30

# Whisper (local)
VOICE_WHISPER_MODE=auto
VOICE_WHISPER_MODEL=openai/whisper-base
VOICE_WHISPER_LANGUAGE=de
VOICE_WHISPER_CACHE_DIR=/home/siddy/.cache/huggingface
VOICE_WHISPER_PRELOAD=true

# LLM
VOICE_LLM_BASE_URL=http://host.docker.internal:8000
VOICE_LLM_MODEL=llama3.2:3b
VOICE_LLM_TIMEOUT_SECONDS=45

# Shelly routing
SHELLY_DEVICE_MAP_FILE=/app/app/config/shelly_devices.json
SHELLY_DEVICE_MAP_JSON=
SHELLY_DEFAULT_COMMAND_PATH=/script/light-control
SHELLY_TIMEOUT_SECONDS=5

# TTS
VOICE_TTS_SHELL_COMMAND=
VOICE_TTS_AUTO_ENABLED=true
VOICE_TTS_LANGUAGE=de
VOICE_READY_ANNOUNCEMENT_ENABLED=true
VOICE_READY_ANNOUNCEMENT_TEXT=Ich bin jetzt einsatzbereit.
VOICE_WAKE_BEEP_ENABLED=true
VOICE_WAKE_BEEP_FREQUENCY_HZ=880
VOICE_WAKE_BEEP_DURATION_MS=120
VOICE_WAKE_BEEP_VOLUME=0.25
```

### Provide Shelly script

A lookup table is used for routing across multiple Shelly devices (room/aliases/group → DNS/IP).
Example file: `voice-pipeline/app/config/shelly_devices.example.json`.

> Important: inside the container, the **example file** is mounted read-only. For production mappings, create your own `voice-pipeline/app/config/shelly_devices.json`.

```bash
cp voice-pipeline/app/config/shelly_devices.example.json \
   voice-pipeline/app/config/shelly_devices.json
```

Example of a real mapping entry:
```json
{
  "id": "livingroom_light",
  "room": "livingroom",
  "group": "livingroom",
  "aliases": ["livingroom", "living room light", "living room lamp"],
  "base_url": "http://livingroom-light.arkham.asylum",
  "command_path": "/script/light-control"
}
```

The reusable Shelly script is located at `shelly_script/shelly_1pm_control.js`.

Quick flow:
1. Open Shelly Web UI → **Scripts**
2. Create new script, paste content from file (same script on every target Shelly)
3. Start script
4. Set a unique DNS/IP entry for each Shelly in `shelly_devices.json`
5. Test with: `http://<SHELLY-IP>/script/light-control?action=off`

Response is JSON with `ok=true|false` and `message`, which is evaluated by the Python pipeline.

Optional: for BLU sensors (Motion / Door-Window), there is a separate gateway script including instructions under `shelly_script/README.md` and `shelly_script/blu-flow-detector-v1.js`.

Without `VOICE_TTS_SHELL_COMMAND`, the pipeline automatically uses `espeak-ng` + `paplay` and tries to play output on **all detected Pulse sinks**.

## 1. Architecture overview

### What does Pi-hole do?
Pi-hole provides the central DNS resolver in the home network. Static DNS entries ensure reliable internal resolution of device and service names.

### What do the Docker services do?
- Mosquitto: MQTT broker, e.g. for Shelly devices or other MQTT-capable devices
- Telegraf: reads MQTT messages and writes them to InfluxDB
- InfluxDB: database storing logged data (e.g. MQTT data)
- Grafana: dashboards and visualization
- Pi-hole: DNS Web UI and local DNS server
- Caddy: reverse proxy for HTTPS/TLS (local certificates in the home network)

### Important MQTT note for Shelly H&T devices
For **Shelly H&T (HT) devices**, the MQTT topic/device name must start with the prefix **`shelly_ht_`**.
Only then can data be correctly recognized by existing Telegraf/Influx/Grafana flows and shown properly in HT dashboards.

### Why `arkham.asylum` internally?
- Consistent, memorable naming scheme for devices and services
- Decouples clients/scripts from changing IP addresses
- Clear separation between internal intranet DNS and public DNS world

## 2. DNS naming concept

### Device mapping
- `<PC_NAME>.arkham.asylum` → `192.168.1.3` (PC)

### Service FQDN mapping (pointing to Raspberry Pi)
- `pihole.arkham.asylum`

Static DNS entries are located in `docker/pihole/custom.list`.

## 3. Step-by-step setup

### Prerequisites
- Docker + Docker Compose plugin (`docker compose`)
- Raspberry Pi host at e.g. `192.168.1.101`
- Access to router/DHCP configuration

## Install Docker in shell

```bash
curl -fsSL https://get.Docker.com -o get-Docker.sh
sudo sh get-Docker.sh
sudo usermod -aG docker $USER
newgrp docker
```

## Stop all Docker instances and delete all data

```bash
# (Warning) simply deletes everything! All data of all Docker containers
docker rm -f $(docker ps -aq) && docker volume rm $(docker volume ls -q) && docker system prune -a --volumes -f

docker compose down -v --remove-orphans

docker network prune -f

# One-command variant (containers + volumes + networks, without deleting images)
docker system prune --volumes -f

docker system prune -a --volumes -f

# if pihole misbehaves:
docker compose stop pihole
docker compose rm -f pihole

sudo rm -rf /home/siddy/syn4ps3h0me/docker/pihole/etc-pihole
sudo rm -rf /home/siddy/syn4ps3h0me/docker/pihole/etc-dnsmasq.d

mkdir -p /home/siddy/syn4ps3h0me/docker/pihole/etc-pihole
mkdir -p /home/siddy/syn4ps3h0me/docker/pihole/etc-dnsmasq.d

docker compose up -d --force-recreate pihole
```

### Prepare configuration
```bash
cp .env .env.local  # optional backup before editing
```

### Secrets in `.env`
Please set the secret variables used in production (examples):
- `MQTT_PASSWORD=...`
- `INFLUXDB_PASSWORD=...`
- `INFLUXDB_WRITE_TOKEN=...`
- `GRAFANA_ADMIN_PASSWORD=...`
- `PIHOLE_API_PASSWORD=...`
- `PIHOLE_ADMIN_PASSWORD=...`
- `OPEN_WEBUI_ADMIN_PASSWORD=...`

Other base values in `.env` (used in production):
- `INTRANET_DOMAIN=arkham.asylum`
- `TZ=Europe/Berlin`

### Start / Stop
```bash
# Start stack
docker compose up -d

# Stop stack
docker compose down
```

### HTTP/HTTPS
With default settings, services are reachable via DNS entries:
-
   → `grafana` `http://nightmaresiddious.arkham.asylum:3000`
   → `pihole` `http://nightmaresiddious.arkham.asylum:8088`
   → `mosquitto` `http://nightmaresiddious.arkham.asylum:1883`

Caddy uses an internal local CA by default (`tls internal`). This allows HTTPS access in the home network without public domains/port forwarding.
Proxy/TLS configuration is in `caddy/config.json` (Caddy JSON config).
Most important variables in `.env`:
- `GRAFANA_DOMAIN=grafana.your-domain.tld`
- `PIHOLE_DOMAIN=pihole.your-domain.tld`
- `LEGACY_HOST_DOMAIN=nightmaresiddious.arkham.asylum` (optional, so access via hostname also works over HTTPS)
- `LEGACY_HOST_IP=192.168.1.101` (optional, so access via host IP also works over HTTPS)

Important:
- On first access, browser will show an untrusted certificate warning (internal CA). This is expected in LAN.
- To remove warnings cleanly, import Caddy root CA on clients.
- If you later use real public domains, you can switch back to Let's Encrypt.

If you come from an older Caddy configuration and the container still starts with old errors, remove old persisted Caddy config once:
```bash
docker compose down
docker volume rm syn4ps3h0me_caddy_config 2>/dev/null || true
docker compose up -d --force-recreate caddy
```

Additionally, direct service ports are enabled again as fallback:
- Grafana direct: `http://nightmaresiddious.arkham.asylum:3000` or `http://192.168.1.101:3000`
- Pi-hole direct: `http://nightmaresiddious.arkham.asylum:8088/admin/` or `http://192.168.1.101:8088/admin/`

Important: these direct ports speak **HTTP**, not HTTPS.
`https://...:3000` or `https://...:8088` leads to browser errors.

### First Pi-hole login
1. Open Pi-hole: `https://pihole.arkham.asylum/admin/` (provided via Caddy reverse proxy).
   Alternative (legacy host): `https://nightmaresiddious.arkham.asylum/admin/`.
2. Log in with `PIHOLE_ADMIN_PASSWORD` from `.env`.
3. Optional theme is controlled via `PIHOLE_WEBTHEME` (default: `default-darker` = “Pi-hole Midnight”).
4. DNS upstream resolvers are set via `PIHOLE_DNS_UPSTREAMS` (default: `1.1.1.1;1.0.0.1;1.1.1.1;9.9.9.9`).
5. Under *Local DNS*, verify entries from `custom.list` are active.

### Switch router / DHCP to Pi-hole DNS
- Set primary DNS server in router to `192.168.1.101`.
- Renew DHCP leases (or reconnect clients) so clients use Pi-hole as DNS.

### Assign fixed IPs via Pi-hole DHCP (optional)
If Pi-hole should also manage DHCP (e.g. for fixed IP assignments), proceed as follows:

1. **Disable router DHCP** (important: only one DHCP server in network).
2. Set these variables in `.env`:
   - `PIHOLE_DHCP_ACTIVE=true`
   - `PIHOLE_DHCP_START=192.168.1.150`
   - `PIHOLE_DHCP_END=192.168.1.220`
   - `PIHOLE_DHCP_ROUTER=192.168.1.1`
   - `PIHOLE_DHCP_LEASETIME=24h`
3. Add static leases in `docker/pihole/etc-dnsmasq.d/04-static-dhcp.conf`:

```ini
# Example (adjust MACs)
dhcp-host=AA:BB:CC:DD:EE:01,192.168.1.3,darksiddious,infinite
dhcp-host=AA:BB:CC:DD:EE:02,192.168.1.101,nightmaresiddious,infinite
```

4. Restart Pi-hole:
```bash
docker compose up -d --force-recreate pihole
```

Note: this procedure matches Pi-hole’s recommended role as central DNS/DHCP service in the LAN.

## 4. Operations documentation

### Pi-hole Docker configuration (according to official Docker variables)
Pi-hole configuration primarily uses `FTLCONF_*` variables:
- API password: `FTLCONF_webserver_api_password` (from `.env`: `PIHOLE_API_PASSWORD`)
- WebUI password (legacy alias): `WEBPASSWORD` (from `.env`: `PIHOLE_ADMIN_PASSWORD`)
- Theme: `FTLCONF_webserver_interface_theme` (from `.env`: `PIHOLE_WEBTHEME`)
- DNS upstream: `FTLCONF_dns_upstreams` (from `.env`: `PIHOLE_DNS_UPSTREAMS`)
- DNSSEC: `FTLCONF_dns_dnssec` (from `.env`: `PIHOLE_DNSSEC=true`)
- Listening mode: `FTLCONF_dns_listeningMode=all`

Apply changes:
```bash
docker compose up -d --force-recreate pihole
```

Note: with an existing persistent volume, an old password may remain active. Then set it explicitly:
```bash
docker compose exec pihole pihole setpassword "$PIHOLE_ADMIN_PASSWORD"
```

### Block lists for ads and malicious domains
The stack includes a custom list in `docker/pihole/adlists.list` (including StevenBlack, RPiList, Firebog, anudeepND).

Apply/update block lists:
```bash
docker compose exec pihole pihole -g
```

Note: `docker/pihole/adlists.list` must use LF line endings (no CRLF), otherwise gravity updates show `Invalid Target ...^M` errors.

Optional checks:
```bash
docker compose exec pihole pihole -q doubleclick.net
docker compose exec pihole pihole -q phishing
```

### Restart behavior
All services run with `restart: unless-stopped` and restart automatically after host reboot.

### Check logs
```bash
# All logs
docker compose logs -f

# Pi-hole logs
docker compose logs -f pihole
```

### Update process
```bash
# Update images
docker compose pull

# Recreate containers with new image
docker compose up -d

# Clean up old orphaned images (optional)
docker image prune -f
```

## 5. Smoke tests (copy/paste)

```bash
# Validate compose file
docker compose config

# Start stack
docker compose up -d

# Check DNS resolution via Pi-hole (explicit DNS server)
nslookup grafana.arkham.asylum 192.168.1.101
nslookup mqtt.arkham.asylum 192.168.1.101
nslookup darksiddious.arkham.asylum 192.168.1.101

# Check reachability
ping -c 2 nightmaresiddious.arkham.asylum
curl -I https://grafana.arkham.asylum
curl -I https://pihole.arkham.asylum/admin/
```

## 6. Uninstall / rollback

For modular removal, use `uninstall.sh`.
The script can remove individual parts:

- Smart Home (mosquitto, influxdb, telegraf, grafana)
- Pi-hole
- Caddy
- Voice pipeline
- LLM chat (open-webui, hailo-ollama)
- optional “Uninstall everything (including Docker)”

Run:
```bash
cd ~/workspace/syn4ps3h0me
chmod +x uninstall.sh
./uninstall.sh
```

Then optionally verify:
```bash
docker compose ps
systemctl status hailo-ollama
```

## 7. Troubleshooting

### Set Pi-hole theme to "Pi-hole Midnight"
Yes. The theme can be set centrally via env variable and then appears in Web Interface/API settings:
- `.env`: `PIHOLE_WEBTHEME=default-darker`

Apply:
```bash
docker compose up -d --force-recreate pihole
```

### Connection refused or TLS errors
Symptom: browser shows `ERR_CONNECTION_REFUSED` or TLS errors on old port URLs.

Background:
- With Caddy, secured access runs via **port 443** by default.
- Direct ports (`3000`, `8088`) are available as HTTP fallback; HTTPS runs via port 443 through Caddy.

Use instead:
```bash
# HTTPS via Caddy
https://grafana.arkham.asylum
https://pihole.arkham.asylum/admin/
https://nightmaresiddious.arkham.asylum/login
https://nightmaresiddious.arkham.asylum/admin/
https://192.168.1.101/login
https://192.168.1.101/admin/

# HTTP fallback directly on service ports
http://192.168.1.101:3000
http://192.168.1.101:8088/admin/
```

### 403 on Pi-hole WebUI (root URL)
Symptom: `https://pihole.arkham.asylum` shows `403 Access denied`.

Background:
- Depending on version/config, Pi-hole may not serve dashboard content on `/`.
- Therefore, the stack includes a redirect from `/` to `/admin/`.

Check:
```bash
curl -I https://pihole.arkham.asylum
curl -I https://pihole.arkham.asylum/admin/
```

Fix:
- Ensure `docker/pihole/lighttpd-external.conf` is mounted.
- Recreate Pi-hole:
```bash
docker compose up -d --force-recreate pihole
```

### Gravity update shows `Invalid Target ...^M`
Symptom: `pihole -g` reports `Invalid Target` for each list and shows `^M` at end of URL.

Cause:
- Windows CRLF (`\r\n`) in `docker/pihole/adlists.list`.

Check:
```bash
cat -vet docker/pihole/adlists.list
```
If `^M$` appears at line endings, the file contains CRLF.

Fix:
```bash
# Normalize to LF on host
sed -i 's/\r$//' docker/pihole/adlists.list

# Reload Pi-hole and rebuild gravity
docker compose restart pihole
docker compose exec pihole pihole -g
```

Additionally, `.gitattributes` in the repo enforces LF for Pi-hole lists/configs.

### DHCP does not assign fixed IPs
Symptom: device does not receive desired IP despite `dhcp-host` entry.

Check:
```bash
docker compose exec pihole pihole-FTL --config dhcp.active
docker compose exec pihole grep -n "^dhcp-host" /etc/dnsmasq.d/04-static-dhcp.conf
```

Fix:
- Check router DHCP is really disabled.
- Ensure MAC address in `dhcp-host` entry is exact.
- Renew DHCP lease on client or reconnect device.

### Port 53 is occupied
Symptom: Pi-hole does not start, error mentions `53/tcp` or `53/udp`.

Check:
```bash
sudo ss -lntup | rg ':53'
```

Fix:
- Disable/reconfigure local DNS resolver on host (e.g. `systemd-resolved`).
- Then restart stack: `docker compose up -d pihole`.

### DNS cache issue
Symptom: old DNS entry still returned after change.

Fix:
- Clear Pi-hole cache (WebUI or `pihole restartdns` in container).
- Clear client DNS cache (OS-dependent).
- Renew client DHCP lease.

### Wrong DNS responses
Symptom: FQDN resolves to wrong IP.

Check:
```bash
cat docker/pihole/custom.list
nslookup telegraf.arkham.asylum 192.168.1.101
```

Fix:
- Correct `custom.list`.
- Reload Pi-hole DNS:
```bash
docker compose exec pihole pihole restartdns
```

---

## Compose design (refactor notes)
- Consistent `container_name` in lowercase kebab-case.
- `hostname` set per service.
- Shared Docker network `intranet` for all services.
- Pi-hole persistence via:
  - `docker/pihole/etc-pihole`
  - `docker/pihole/etc-dnsmasq.d`
  - `docker/pihole/custom.list`
  - `docker/pihole/adlists.list`

Details on changes and ports are documented in `CHANGELOG.md`.

## Grafana

### Adjust power price

To show costs correctly in the dashboard,
replace the default value `0.3577` with your own electricity price
in `shelly-overview.json` in the
**Total costs** section.
