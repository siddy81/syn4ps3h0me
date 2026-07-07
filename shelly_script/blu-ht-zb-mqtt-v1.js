let CONFIG = {
    topic_base: "shellies/blu/shelly_blu_hT_zb",

    qos: 1,
    retain: true,
    scan_active: false,
    debug: true,

    publish_telemetry_every_sec: 300,

    temperature_delta: 0.1,
    humidity_delta: 1,

    devices: [
        {
            mac: "c0:2c:ed:2c:69:7d",
            name: "Terrasse Klima"
        }
    ]
};

let deviceByMac = {};
let deviceState = {};

function _consoleLog(msg) {
    if (typeof console !== "undefined" && console && typeof console.log === "function") {
        console.log(msg);
    } else {
        print(msg);
    }
}

function nowUnix() {
    let s = Shelly.getComponentStatus("sys");
    if (s && typeof s.unixtime === "number") return s.unixtime;
    return 0;
}

function logInfo(msg) {
    _consoleLog("[BLU-H&T->MQTT][INFO][" + nowUnix() + "] " + msg);
}

function logWarn(msg) {
    _consoleLog("[BLU-H&T->MQTT][WARN][" + nowUnix() + "] " + msg);
}

function logDebug(msg) {
    if (CONFIG.debug) {
        _consoleLog("[BLU-H&T->MQTT][DEBUG][" + nowUnix() + "] " + msg);
    }
}

function getTopicPrefix(device) {
    return CONFIG.topic_base + "/" + device.name;
}

function mqttPublish(topic, payload, retainOverride) {
    if (!MQTT.isConnected()) {
        logWarn("MQTT nicht verbunden -> drop: topic=" + topic + " payload=" + payload);
        return false;
    }

    let retain = (typeof retainOverride === "boolean") ? retainOverride : CONFIG.retain;
    let ok = MQTT.publish(topic, payload, CONFIG.qos, retain);

    if (!ok) {
        logWarn("MQTT publish FEHLER: topic=" + topic);
    } else {
        logDebug("MQTT publish OK: topic=" + topic + " retain=" + retain);
    }

    return ok;
}

function ensureDeviceState(mac) {
    if (!deviceState[mac]) {
        deviceState[mac] = {
            lastPid: null,
            lastTemperature: null,
            lastHumidity: null,
            lastBattery: null,
            lastRssi: null,
            lastButton: null,
            lastTelemetryTs: 0
        };
    }
    return deviceState[mac];
}

function readUInt16LE(bytes, offset) {
    return bytes[offset] | (bytes[offset + 1] << 8);
}

function readInt16LE(bytes, offset) {
    let v = readUInt16LE(bytes, offset);
    if (v & 0x8000) v = v - 0x10000;
    return v;
}

function readUInt24LE(bytes, offset) {
    return bytes[offset] | (bytes[offset + 1] << 8) | (bytes[offset + 2] << 16);
}

function readUInt32LE(bytes, offset) {
    return (bytes[offset]) |
        (bytes[offset + 1] << 8) |
        (bytes[offset + 2] << 16) |
        (bytes[offset + 3] << 24);
}

let BTHOME_SIZES = {
    0x00: 1,
    0x01: 1,
    0x02: 2,
    0x03: 2,
    0x15: 1,
    0x2E: 1,
    0x3A: 1,
    0x45: 2,
    0xF0: 2,
    0xF1: 4,
    0xF2: 3
};

function parseBTHome(dataStr) {
    if (!dataStr || dataStr.length < 1) {
        return null;
    }

    let bytes = [];
    let i;

    for (i = 0; i < dataStr.length; i++) {
        bytes.push(dataStr.charCodeAt(i));
    }

    let offset = 0;

    if (bytes.length >= 2 && bytes[0] === 0xD2 && bytes[1] === 0xFC) {
        offset = 2;
    }

    if (offset >= bytes.length) {
        return null;
    }

    let devInfo = bytes[offset++];
    let version = (devInfo >> 5) & 0x07;
    let encrypted = (devInfo & 0x01) === 1;

    if (version !== 2) {
        logDebug("unsupported BTHome version=" + version);
        return null;
    }

    if (encrypted) {
        logWarn("BTHome payload encrypted -> ignoriert");
        return null;
    }

    let out = {};

    while (offset < bytes.length) {
        let id = bytes[offset++];
        let size = BTHOME_SIZES[id];

        if (typeof size === "undefined") {
            logDebug("unbekannte object id=0x" + id.toString(16) + " -> stop");
            break;
        }

        if (offset + size > bytes.length) {
            logDebug("unvollständige payload bei id=0x" + id.toString(16));
            break;
        }

        if (id === 0x00) {
            out.pid = bytes[offset];
        } else if (id === 0x01) {
            out.battery = bytes[offset];
        } else if (id === 0x02) {
            out.temperature = readInt16LE(bytes, offset) * 0.01;
        } else if (id === 0x03) {
            out.humidity = readUInt16LE(bytes, offset) * 0.01;
        } else if (id === 0x15) {
            out.battery_low = bytes[offset];
        } else if (id === 0x2E) {
            out.humidity = bytes[offset];
        } else if (id === 0x3A) {
            out.button = bytes[offset];
        } else if (id === 0x45) {
            out.temperature = readInt16LE(bytes, offset) * 0.1;
        } else if (id === 0xF0) {
            out.device_type_id = readUInt16LE(bytes, offset);
        } else if (id === 0xF1) {
            out.firmware_version_u32 = readUInt32LE(bytes, offset);
        } else if (id === 0xF2) {
            out.firmware_version_u24 = readUInt24LE(bytes, offset);
        }

        offset += size;
    }

    if (typeof out.temperature === "number") {
        out.temperature = Math.round(out.temperature * 10) / 10;
    }

    if (typeof out.humidity === "number") {
        out.humidity = Math.round(out.humidity * 10) / 10;
    }

    return out;
}

function numberChanged(current, previous, delta) {
    if (typeof current !== "number") return false;
    if (previous === null || typeof previous !== "number") return true;
    return Math.abs(current - previous) >= delta;
}

function publishEvent(device, eventName, payload) {
    let msg = {
        ts: nowUnix(),
        reason: eventName,
        mac: device.mac,
        name: device.name,
        type: "ht"
    };

    let k;
    for (k in payload) {
        msg[k] = payload[k];
    }

    mqttPublish(getTopicPrefix(device) + "/event", JSON.stringify(msg), false);
}

function publishTelemetry(device, data, reason) {
    let payload = {
        ts: nowUnix(),
        reason: reason || "scan",
        mac: device.mac,
        name: device.name,
        type: "ht"
    };

    if (typeof data.temperature === "number") payload.temperature = data.temperature;
    if (typeof data.humidity === "number") payload.humidity = data.humidity;
    if (typeof data.battery === "number") payload.battery = data.battery;
    if (typeof data.battery_low === "number") payload.battery_low = data.battery_low;
    if (typeof data.rssi === "number") payload.rssi = data.rssi;
    if (typeof data.pid === "number") payload.pid = data.pid;
    if (typeof data.button === "number") payload.button = data.button;
    if (typeof data.device_type_id === "number") payload.device_type_id = data.device_type_id;

    mqttPublish(getTopicPrefix(device) + "/telemetry", JSON.stringify(payload), false);
    logDebug("Telemetry gesendet: " + device.name + " -> " + JSON.stringify(payload));
}

function publishMeasurements(device, data) {
    let st = ensureDeviceState(device.mac);
    let prefix = getTopicPrefix(device);
    let changed = false;

    if (numberChanged(data.temperature, st.lastTemperature, CONFIG.temperature_delta)) {
        mqttPublish(prefix + "/temperature", String(data.temperature), true);
        st.lastTemperature = data.temperature;
        changed = true;
        logInfo(device.name + " temperature -> " + data.temperature);
    }

    if (numberChanged(data.humidity, st.lastHumidity, CONFIG.humidity_delta)) {
        mqttPublish(prefix + "/humidity", String(data.humidity), true);
        st.lastHumidity = data.humidity;
        changed = true;
        logInfo(device.name + " humidity -> " + data.humidity);
    }

    if (typeof data.battery === "number" && data.battery !== st.lastBattery) {
        mqttPublish(prefix + "/battery", String(data.battery), true);
        st.lastBattery = data.battery;
        changed = true;
        logInfo(device.name + " battery -> " + data.battery);
    }

    if (typeof data.rssi === "number" && data.rssi !== st.lastRssi) {
        mqttPublish(prefix + "/rssi", String(data.rssi), true);
        st.lastRssi = data.rssi;
    }

    if (typeof data.button === "number") {
        let buttonText = "unknown";

        if (data.button === 1) {
            buttonText = "single_press";
        } else if (data.button === 0x80 || data.button === 0xFE) {
            buttonText = "hold";
        }

        mqttPublish(prefix + "/button", buttonText, false);
        publishEvent(device, "button", {
            button: data.button,
            button_state: buttonText,
            temperature: data.temperature,
            humidity: data.humidity,
            battery: data.battery,
            rssi: data.rssi,
            pid: data.pid
        });

        changed = true;
    }

    if (changed) {
        publishEvent(device, "measurement_changed", {
            temperature: data.temperature,
            humidity: data.humidity,
            battery: data.battery,
            battery_low: data.battery_low,
            rssi: data.rssi,
            pid: data.pid
        });
    }

    return changed;
}

function shouldPublishTelemetry(device) {
    let st = ensureDeviceState(device.mac);
    let now = nowUnix();

    if (st.lastTelemetryTs === 0) {
        st.lastTelemetryTs = now;
        return true;
    }

    if ((now - st.lastTelemetryTs) >= CONFIG.publish_telemetry_every_sec) {
        st.lastTelemetryTs = now;
        return true;
    }

    return false;
}

function onScan(event, result) {
    if (event !== BLE.Scanner.SCAN_RESULT) return;
    if (!result || !result.addr) return;

    let mac = result.addr.toLowerCase();
    let device = deviceByMac[mac];

    if (!device) {
        return;
    }

    if (!result.service_data || !result.service_data.fcd2) {
        logDebug(device.name + ": kein service_data.fcd2 vorhanden -> ignoriert");
        return;
    }

    let parsed = parseBTHome(result.service_data.fcd2);

    if (!parsed) {
        logDebug(device.name + ": BTHome parsing ergab null -> ignoriert");
        return;
    }

    parsed.rssi = result.rssi;

    let st = ensureDeviceState(mac);

    if (typeof parsed.pid === "number") {
        if (parsed.pid === st.lastPid && typeof parsed.button !== "number") {
            logDebug(device.name + ": Duplicate PID=" + parsed.pid + " -> ignoriert");
            return;
        }

        st.lastPid = parsed.pid;
    }

    let changed = publishMeasurements(device, parsed);

    if (changed || shouldPublishTelemetry(device)) {
        publishTelemetry(device, parsed, changed ? "changed" : "periodic");
    }
}

function initDevices() {
    let i;

    for (i = 0; i < CONFIG.devices.length; i++) {
        let d = CONFIG.devices[i];

        if (!d || !d.mac || !d.name) {
            logWarn("Ungueltiger Geräte-Eintrag bei index=" + i + " (mac/name fehlen)");
            continue;
        }

        d.mac = d.mac.toLowerCase();
        deviceByMac[d.mac] = d;
        ensureDeviceState(d.mac);

        logInfo("Gerät registriert: name=" + d.name + " mac=" + d.mac);
    }
}

function publishStartupStatus() {
    let count = 0;
    let i;

    for (i = 0; i < CONFIG.devices.length; i++) {
        let d = CONFIG.devices[i];

        if (!d || !d.mac || !d.name) continue;

        count++;

        mqttPublish(
            getTopicPrefix(d) + "/status",
            JSON.stringify({
                ts: nowUnix(),
                script: "running",
                mac: d.mac,
                name: d.name,
                type: "ht"
            }),
            true
        );
    }

    mqttPublish(
        CONFIG.topic_base + "/gateway/ht-status",
        JSON.stringify({
            ts: nowUnix(),
            script: "running",
            device_count: count
        }),
        true
    );
}

function init() {
    logInfo("Initialisierung gestartet...");

    if (typeof BLE === "undefined" || !BLE.Scanner) {
        logWarn("BLE Scanner nicht verfügbar auf diesem Gerät/FW.");
        return;
    }

    initDevices();

    BLE.Scanner.Subscribe(onScan);
    logDebug("BLE Scanner callback registriert");

    let ok = BLE.Scanner.Start({
        duration_ms: BLE.Scanner.INFINITE_SCAN,
        active: CONFIG.scan_active,
        filter: {}
    });

    if (!ok) {
        logWarn("BLE Scan Start fehlgeschlagen");
        return;
    }

    logInfo("Script läuft.");
    publishStartupStatus();
}

init();