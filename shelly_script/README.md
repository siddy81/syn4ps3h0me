# Shelly BLU Gateway Scripts

In diesem Bereich liegen Shelly-Skripte, die direkt auf einem Shelly-Gerät unter **Scripts** eingefügt werden.

Aktuell ist nur ein Script vorhanden:

- `blu-flow-detector-v1.js`

Weitere Scripts werden später folgen.

## Zweck

`blu-flow-detector-v1.js` macht einen Shelly Plus/Pro mit Script-Unterstützung zum Bluetooth-Gateway für ausgewählte **Shelly BLU Sensoren** und veröffentlicht deren Zustände per **MQTT**.

Der aktuelle Fokus liegt auf:

- **[Shelly BLU Motion](https://amzn.to/4s26ePU)**
- **[Shelly BLU Door/Window](https://amzn.to/3O5aIav)**

## Wichtig

- Das Script muss auf den **Shellys laufen, die als Gateway für die BLU-Sensoren verwendet werden**.
- Das Script muss in der **Shelly Web UI** unter **Scripts** eingefügt werden.
- Danach **CONFIG anpassen**, **speichern** und **starten**.
- Die verwendeten **Shelly BLU Sensoren müssen unverschlüsselt senden**:
    - **security = off**
- MQTT muss auf dem Shelly korrekt eingerichtet sein.

## Installation

1. Shelly Web UI öffnen
2. **Scripts** auswählen
3. Neues Script anlegen
4. Inhalt von `blu-flow-detector-v1.js` einfügen
5. Script z. B. als `blu-flow-detector-v1` speichern
6. `CONFIG` anpassen (Wichtig- ihr müsst die MAC-Adressen eurer Sensoren an die richtige Stelle einfügen)
7. Script starten

## Was das Script macht

- empfängt BLE-Daten von mehreren BLU-Sensoren
- erkennt Bewegungs- und Tür-/Fensterzustände
- veröffentlicht Zustände per MQTT
- sendet zusätzliche Telemetrie wie z. B.:
    - RSSI
    - Batterie
    - Helligkeit
- unterstützt einfache Richtungs-/Ablauf-Erkennung:
    - **enter**
    - **exit**

## Konfiguration

Im `CONFIG`-Block werden u. a. definiert:

- MQTT Topic-Basis
- Debug-Verhalten
- Scan-Modus
- bekannte Geräte mit:
    - MAC-Adresse
    - Name
    - Typ
- optionale Flow-Gruppen zur Sequenz-Erkennung

## Hinweis

Derzeit unterstützt das vorhandene Script **Motion** sowie **Door/Window**.  
**Shelly BLU H&T ist in diesem Script aktuell nicht umgesetzt.** Das kann in späteren Scripts ergänzt werden.