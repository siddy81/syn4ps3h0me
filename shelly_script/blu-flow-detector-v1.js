// ============================================================================
// Shelly Plus 1PM Script: Multi Shelly BLU (Motion + Door/Window) -> MQTT
// ============================================================================
// Einfügen in: Shelly Web UI -> Scripts -> Add Script
// Danach CONFIG anpassen, Save, Start
// Name blu-flow-detector-v1
// Wichtig: Die Shelly-BLU müssen unverschlüsselt senden! D.h. security = off
// ============================================================================

let CONFIG = {
    // MQTT Topic Basis
    topic_base: "shellies/blu",

    // Default-Timer für Motion-Sensoren, falls kein motion=0 kommt
    default_no_motion_after_sec: 90,

    // MQTT Publish Optionen
    qos: 1,
    retain: true,

    // BLE Scan: false = passiv (reicht normalerweise)
    scan_active: false,

    // true = mehr Logs (sehr hilfreich beim Debuggen)
    debug: true,

    // ------------------------------------------------------------------------
    // Geräte-Liste (mehrere BLU Sensoren pro Shelly Plus möglich)
    // type: "motion" | "door" | "auto"
    //  - motion: erwartet hauptsächlich motion-Feld
    //  - door:   erwartet hauptsächlich window-Feld
    //  - auto:   erkennt anhand eingehender Daten
    // ------------------------------------------------------------------------
    devices: [
        {
            mac: "38:39:8f:9d:57:12",
            name: "Schlafzimmer Bewegung",
            type: "motion",
            no_motion_after_sec: 90
        }    ,
        {
            mac: "e8:e0:7e:cc:00:eb",
            name: "Wohnzimmer Bewegung",
            type: "motion",
            no_motion_after_sec: 90
        },
        {
            mac: "3c:2e:f5:73:1d:e4",
            name: "Essecke Bewegung",
            type: "motion",
            no_motion_after_sec: 90
        },
        {
            mac: "38:39:8f:98:85:b9",
            name: "Flur Bewegung",
            type: "motion",
            no_motion_after_sec: 90
        },

        {
            mac: "f4:b3:b1:82:ce:fb",
            name: "Terrassentür",
            type: "door",
            no_motion_after_sec: 90
        },
        {
            mac: "38:39:8f:98:62:fe",
            name: "Wohnungstür",
            type: "door",
            no_motion_after_sec: 90
        },
        {
            mac: "b0:c7:de:06:63:47",
            name: "Balkontür",
            type: "door",
            no_motion_after_sec: 90
        }
        // Beispiel:
        // {
        //     mac: "34:85:18:aa:bb:cc",
        //     name: "haustuer",
        //     type: "door"
        // }
    ],

    // ------------------------------------------------------------------------
    // Optionale Sequenz-Erkennung (Haus betreten / verlassen)
    // enter: door(open) -> motion(1)
    // exit:  motion(1)  -> door(open)
    // motion_macs erlaubt mehrere Bewegungsmelder pro Gruppe
    // ------------------------------------------------------------------------
    flow_groups: [
        // Beispiel:
        // {
        //     name: "eingang",
        //     door_mac: "34:85:18:aa:bb:cc",
        //     motion_macs: ["38:39:8f:9d:57:12", "e8:e0:7e:cc:00:eb"],
        //     sequence_timeout_sec: 20,
        //     door_open_value: 1
        // }
         {
             name: "Terrassentür eingang",
             door_mac: "f4:b3:b1:82:ce:fb",
             motion_mac: "e8:e0:7e:cc:00:eb",
             sequence_timeout_sec: 20,
             door_open_value: 1
         },
        {
            name: "Wohnungstür eingang",
            door_mac: "38:39:8f:98:62:fe",
            motion_mac: "38:39:8f:98:85:b9",
            sequence_timeout_sec: 20,
            door_open_value: 1
        },
        {
            name: "Balkontür eingang",
            door_mac: "b0:c7:de:06:63:47",
            motion_mac: "3c:2e:f5:73:1d:e4",
            sequence_timeout_sec: 20,
            door_open_value: 1
        }
    ]
};

// Rückwärtskompatibilität (falls alte Felder verwendet werden)
if ((!CONFIG.devices || CONFIG.devices.length === 0) && CONFIG.sensor_mac && CONFIG.device_name) {
    CONFIG.devices = [{
        mac: CONFIG.sensor_mac,
        name: CONFIG.device_name,
        type: "motion",
        no_motion_after_sec: CONFIG.no_motion_after_sec || CONFIG.default_no_motion_after_sec
    }];
}

let deviceByMac = {};
let deviceState = {}; // per MAC: {lastPid, lastMotionState, lastWindowState, offTimer}
let flowGroups = [];
let flowState = {};   // per group name: {lastType, lastTs, lastMac}

// ---------- Logging ----------
function _consoleLog(msg) {
    if (typeof console !== "undefined" && console && typeof console.log === "function") {
        console.log(msg);
    } else {
        print(msg);
    }
}

function _ts() {
    let s = Shelly.getComponentStatus("sys");
    if (s && typeof s.unixtime === "number" && s.unixtime > 0) {
        return s.unixtime;
    }
    return 0;
}

function logInfo(msg) {
    _consoleLog("[BLU->MQTT][INFO][" + _ts() + "] " + msg);
}

function logWarn(msg) {
    _consoleLog("[BLU->MQTT][WARN][" + _ts() + "] " + msg);
}

function logDebug(msg) {
    if (CONFIG.debug) {
        _consoleLog("[BLU->MQTT][DEBUG][" + _ts() + "] " + msg);
    }
}
// ----------------------------

function nowUnix() {
    let s = Shelly.getComponentStatus("sys");
    if (s && typeof s.unixtime === "number") return s.unixtime;
    return 0;
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

    if (ok) {
        logDebug("MQTT publish OK: topic=" + topic + " retain=" + retain + " qos=" + CONFIG.qos);
    } else {
        logWarn("MQTT publish FEHLER: topic=" + topic);
    }

    return ok;
}

function ensureDeviceState(mac) {
    if (!deviceState[mac]) {
        deviceState[mac] = {
            lastPid: null,
            lastMotionState: null,
            lastWindowState: null,
            offTimer: null
        };
    }
    return deviceState[mac];
}

function inferType(device, parsed) {
    if (device.type && device.type !== "auto") return device.type;
    if (parsed && typeof parsed.motion === "number") return "motion";
    if (parsed && typeof parsed.window === "number") return "door";
    return "auto";
}

function buildCommonPayload(device, reason) {
    return {
        ts: nowUnix(),
        reason: reason || "unknown",
        mac: device.mac,
        name: device.name,
        type: device.type || "auto"
    };
}

function publishEvent(device, eventName, payload) {
    let msg = buildCommonPayload(device, eventName);
    let k;

    if (payload) {
        for (k in payload) {
            msg[k] = payload[k];
        }
    }

    mqttPublish(getTopicPrefix(device) + "/event", JSON.stringify(msg), false);
    logInfo("Event gesendet: " + device.name + " event=" + eventName);
}

function publishMotion(device, stateText, reason, extra) {
    let st = ensureDeviceState(device.mac);
    let prefix = getTopicPrefix(device);

    if (stateText !== st.lastMotionState) {
        mqttPublish(prefix + "/motion", stateText, true);
        st.lastMotionState = stateText;
        logInfo(device.name + " motion -> " + stateText + " (reason=" + reason + ")");
    } else {
        logDebug(device.name + " motion unverändert (" + stateText + ")");
    }

    let ev = {
        state: stateText
    };

    if (extra) {
        if (typeof extra.motion === "number") ev.motion = extra.motion;
        if (typeof extra.window === "number") ev.window = extra.window;
        if (typeof extra.rssi === "number") ev.rssi = extra.rssi;
        if (typeof extra.battery === "number") ev.battery = extra.battery;
        if (typeof extra.illuminance === "number") ev.illuminance = extra.illuminance;
        if (typeof extra.pid === "number") ev.pid = extra.pid;
    }

    publishEvent(device, reason || "motion_state", ev);
}

function publishWindow(device, windowValue, reason, extra) {
    let st = ensureDeviceState(device.mac);
    let prefix = getTopicPrefix(device);
    let stateText = (windowValue === 1) ? "OPEN" : "CLOSED";

    if (windowValue !== st.lastWindowState) {
        mqttPublish(prefix + "/window", stateText, true);
        st.lastWindowState = windowValue;
        logInfo(device.name + " window -> " + stateText + " (reason=" + reason + ")");
    } else {
        logDebug(device.name + " window unverändert (" + stateText + ")");
    }

    let ev = {
        window: windowValue,
        window_state: stateText
    };

    if (extra) {
        if (typeof extra.motion === "number") ev.motion = extra.motion;
        if (typeof extra.rssi === "number") ev.rssi = extra.rssi;
        if (typeof extra.battery === "number") ev.battery = extra.battery;
        if (typeof extra.illuminance === "number") ev.illuminance = extra.illuminance;
        if (typeof extra.pid === "number") ev.pid = extra.pid;
    }

    publishEvent(device, reason || "window_state", ev);
}

function publishTelemetry(device, payload, reason) {
    let data = buildCommonPayload(device, reason || "scan");

    if (payload) {
        if (typeof payload.motion === "number") data.motion = payload.motion;
        if (typeof payload.window === "number") data.window = payload.window;
        if (typeof payload.battery === "number") data.battery = payload.battery;
        if (typeof payload.illuminance === "number") data.illuminance = payload.illuminance;
        if (typeof payload.rssi === "number") data.rssi = payload.rssi;
        if (typeof payload.pid === "number") data.pid = payload.pid;
    }

    mqttPublish(getTopicPrefix(device) + "/telemetry", JSON.stringify(data), false);
    logDebug("Telemetry gesendet: " + device.name + " -> " + JSON.stringify(data));
}

function clearOffTimer(device) {
    let st = ensureDeviceState(device.mac);
    if (st.offTimer !== null) {
        Timer.clear(st.offTimer);
        st.offTimer = null;
        logDebug(device.name + " OFF-Timer gelöscht");
    }
}

function scheduleOffTimeout(device, extra) {
    let st = ensureDeviceState(device.mac);
    let timeoutSec = device.no_motion_after_sec || CONFIG.default_no_motion_after_sec;

    clearOffTimer(device);
    st.offTimer = Timer.set(timeoutSec * 1000, false, function () {
        logInfo(device.name + " Timeout erreicht (" + timeoutSec + "s) -> motion OFF");
        publishMotion(device, "OFF", "timeout", extra || null);
        st.offTimer = null;
    });

    logDebug(device.name + " OFF-Timer gesetzt auf " + timeoutSec + "s");
}

function publishFlowDirection(group, direction, triggerMac) {
    let topic = CONFIG.topic_base + "/group/" + group.name;
    let payload = {
        ts: nowUnix(),
        group: group.name,
        direction: direction,
        door_mac: group.door_mac,
        motion_mac: group.motion_macs[0],
        motion_macs: group.motion_macs,
        trigger_mac: triggerMac
    };

    mqttPublish(topic + "/direction", direction, true);
    mqttPublish(topic + "/event", JSON.stringify(payload), false);
    logInfo("Flow erkannt: group=" + group.name + " direction=" + direction);
}

function trackFlowGroups(device, parsed) {
    let isMotionTrigger = (typeof parsed.motion === "number" && parsed.motion === 1);
    let isDoorTrigger = (typeof parsed.window === "number");
    let i;

    if (!isMotionTrigger && !isDoorTrigger) return;

    for (i = 0; i < flowGroups.length; i++) {
        let group = flowGroups[i];
        let role = null;
        let now = nowUnix();
        let timeoutSec = group.sequence_timeout_sec || 20;
        let st = flowState[group.name];

        if (isMotionTrigger && group.motion_macs.indexOf(device.mac) !== -1) {
            role = "motion";
        }

        if (device.mac === group.door_mac && isDoorTrigger) {
            let doorOpenValue = (typeof group.door_open_value === "number") ? group.door_open_value : 1;
            if (parsed.window === doorOpenValue) {
                role = "door";
            }
        }

        if (!role) continue;

        if (st.lastType && st.lastType !== role && (now - st.lastTs) <= timeoutSec) {
            if (st.lastType === "door" && role === "motion") {
                publishFlowDirection(group, "enter", device.mac);
            } else if (st.lastType === "motion" && role === "door") {
                publishFlowDirection(group, "exit", device.mac);
            }
            st.lastType = null;
            st.lastTs = 0;
            st.lastMac = null;
        } else {
            st.lastType = role;
            st.lastTs = now;
            st.lastMac = device.mac;
            logDebug("Flow Merker: group=" + group.name + " role=" + role + " mac=" + device.mac);
        }
    }
}

// BTHome object sizes (subset + wichtige IDs)
// 0x21 motion, 0x2D window, 0x05 illuminance, 0x01 battery, 0x00 pid
let BTHOME_SIZES = {
    0x00: 1,
    0x01: 1,
    0x05: 3,
    0x21: 1,
    0x2D: 1,
    0x3A: 1,
    0x3F: 2
};

function parseBTHome(dataStr) {
    if (!dataStr || dataStr.length < 1) {
        logDebug("parseBTHome: leere payload");
        return null;
    }

    let bytes = [];
    let i;
    for (i = 0; i < dataStr.length; i++) {
        bytes.push(dataStr.charCodeAt(i));
    }

    let offset = 0;

    // Manche APIs liefern UUID-Bytes (D2 FC) am Anfang mit
    if (bytes.length >= 2 && bytes[0] === 0xD2 && bytes[1] === 0xFC) {
        offset = 2;
    }
    if (offset >= bytes.length) {
        logDebug("parseBTHome: ungültiger offset");
        return null;
    }

    let devInfo = bytes[offset++];
    let version = (devInfo >> 5) & 0x07;
    let encrypted = (devInfo & 0x01) === 1;

    if (version !== 2) {
        logDebug("parseBTHome: unsupported version=" + version);
        return null;
    }
    if (encrypted) {
        logDebug("parseBTHome: payload encrypted -> ignoriert");
        return null;
    }

    let out = {};

    while (offset < bytes.length) {
        let id = bytes[offset++];
        let size = BTHOME_SIZES[id];

        if (typeof size === "undefined") {
            logDebug("parseBTHome: unbekannte object id=0x" + id.toString(16) + " -> stop");
            break;
        }
        if (offset + size > bytes.length) {
            logDebug("parseBTHome: unvollständige payload bei id=0x" + id.toString(16));
            break;
        }

        if (id === 0x00) {
            out.pid = bytes[offset];
        } else if (id === 0x01) {
            out.battery = bytes[offset];
        } else if (id === 0x05) {
            // uint24 LE * 0.01 lux
            out.illuminance = (
                (bytes[offset]) |
                (bytes[offset + 1] << 8) |
                (bytes[offset + 2] << 16)
            ) * 0.01;
        } else if (id === 0x21) {
            out.motion = bytes[offset]; // 0/1
        } else if (id === 0x2D) {
            out.window = bytes[offset]; // 0/1 (falls vorhanden)
        }

        offset += size;
    }

    return out;
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

    let p = parseBTHome(result.service_data.fcd2);
    if (!p) {
        logDebug(device.name + ": BTHome parsing ergab null -> ignoriert");
        return;
    }

    let st = ensureDeviceState(mac);

    // Duplicate-Filter über PID pro Gerät
    if (typeof p.pid === "number") {
        if (p.pid === st.lastPid) {
            logDebug(device.name + ": Duplicate PID=" + p.pid + " -> ignoriert");
            return;
        }
        st.lastPid = p.pid;
    }

    if (!device.type || device.type === "auto") {
        device.type = inferType(device, p);
    }

    let extra = {
        motion: p.motion,
        window: p.window,
        rssi: result.rssi,
        battery: p.battery,
        illuminance: p.illuminance,
        pid: p.pid
    };

    publishTelemetry(device, extra, "scan");

    if (typeof p.motion === "number") {
        if (p.motion === 1) {
            publishMotion(device, "ON", "sensor_motion", extra);
            scheduleOffTimeout(device, extra);
        } else {
            publishMotion(device, "OFF", "sensor_clear", extra);
            clearOffTimer(device);
        }
    }

    if (typeof p.window === "number") {
        publishWindow(device, p.window, "sensor_window", extra);
    }

    trackFlowGroups(device, p);
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
        d.type = d.type || "auto";

        if (!d.no_motion_after_sec || d.no_motion_after_sec < 1) {
            d.no_motion_after_sec = CONFIG.default_no_motion_after_sec;
        }

        deviceByMac[d.mac] = d;
        ensureDeviceState(d.mac);

        logInfo("Gerät registriert: name=" + d.name + " mac=" + d.mac + " type=" + d.type);
    }
}

function initFlowGroups() {
    let i;
    flowGroups = [];

    for (i = 0; i < CONFIG.flow_groups.length; i++) {
        let g = CONFIG.flow_groups[i];
        if (!g || !g.name || !g.door_mac) {
            logWarn("Flow-Group index=" + i + " ungültig (name/door_mac benötigt)");
            continue;
        }

        g.door_mac = g.door_mac.toLowerCase();

        if (!g.motion_macs || g.motion_macs.length === 0) {
            g.motion_macs = [];
            if (g.motion_mac) {
                g.motion_macs.push(g.motion_mac);
            }
        }

        let j;
        for (j = 0; j < g.motion_macs.length; j++) {
            g.motion_macs[j] = g.motion_macs[j].toLowerCase();
        }

        if (g.motion_macs.length === 0) {
            logWarn("Flow-Group index=" + i + " ungültig (mind. eine motion_mac/motion_macs benötigt)");
            continue;
        }

        g.sequence_timeout_sec = g.sequence_timeout_sec || 20;

        flowGroups.push(g);
        flowState[g.name] = {
            lastType: null,
            lastTs: 0,
            lastMac: null
        };

        logInfo("Flow-Group registriert: " + g.name + " (door=" + g.door_mac + ", motion_count=" + g.motion_macs.length + ")");
    }
}

function publishStartupStatus() {
    let i;

    for (i = 0; i < CONFIG.devices.length; i++) {
        let d = CONFIG.devices[i];
        if (!d || !d.mac || !d.name) continue;

        mqttPublish(
            getTopicPrefix(d) + "/status",
            JSON.stringify({
                ts: nowUnix(),
                script: "running",
                mac: d.mac,
                name: d.name,
                type: d.type,
                timeout_sec: d.no_motion_after_sec
            }),
            true
        );
    }

    mqttPublish(
        CONFIG.topic_base + "/gateway/status",
        JSON.stringify({
            ts: nowUnix(),
            script: "running",
            device_count: CONFIG.devices.length,
            flow_group_count: flowGroups.length
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
    initFlowGroups();

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

    logInfo("Script läuft. Registrierte Geräte=" + Object.keys(deviceByMac).length);
    publishStartupStatus();
}

init();
