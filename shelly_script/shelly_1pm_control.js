/*
 * Shelly 1PM reusable script with self-registration + heartbeat.
 * Endpoint: GET /script/light-control?action=on|off|toggle
 */
let CONFIG = {
  endpoint_name: "light-control",
  relay_id: 0,
  central_base_url: "http://192.168.1.101:8091",
  registration_token: "CHANGE_ME",
  device_id: "wohnzimmer_licht",
  room: "wohnzimmer",
  group: "lichter",
  aliases: ["wohnzimmerlicht", "wohnzimmer lampe"],
  heartbeat_interval_sec: 30,
  command_path: "/script/light-control",
  capabilities: ["switch"]
};

function sendJson(response, code, payload) {
  response.code = code;
  response.headers = [["Content-Type", "application/json"]];
  response.body = JSON.stringify(payload);
  response.send();
}

function getQueryParam(query, key) {
  if (!query) return null;
  let parts = query.split("&");
  for (let i = 0; i < parts.length; i++) {
    let kv = parts[i].split("=");
    if (kv[0] === key) {
      return kv.length > 1 ? kv[1] : "";
    }
  }
  return null;
}

function postJson(url, payload, cb) {
  Shelly.call("HTTP.Request", {
    method: "POST",
    url: url,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    timeout: 5,
  }, function (result, errCode, errMsg) {
    if (errCode !== 0) {
      cb(null, errCode, errMsg);
      return;
    }
    cb(result, 0, null);
  });
}

function registerAtCentral() {
  let payload = {
    id: CONFIG.device_id,
    type: "shelly_1pm",
    room: CONFIG.room,
    group: CONFIG.group,
    aliases: CONFIG.aliases,
    capabilities: CONFIG.capabilities,
    base_url: "http://" + Shelly.getComponentStatus("wifi").sta_ip,
    command_path: CONFIG.command_path,
    registration_token: CONFIG.registration_token,
  };

  postJson(CONFIG.central_base_url + "/api/devices/register", payload, function (_, errCode, errMsg) {
    if (errCode !== 0) {
      print("[registry] register failed (local switching continues): " + errMsg);
      return;
    }
    print("[registry] register ok: " + CONFIG.device_id);
  });
}

function sendHeartbeat() {
  postJson(CONFIG.central_base_url + "/api/devices/heartbeat", { id: CONFIG.device_id }, function (_, errCode, errMsg) {
    if (errCode !== 0) {
      print("[registry] heartbeat failed: " + errMsg);
      return;
    }
    print("[registry] heartbeat ok: " + CONFIG.device_id);
  });
}

let registeredPath = HTTPServer.registerEndpoint(CONFIG.endpoint_name, function (request, response) {
  let action = getQueryParam(request.query, "action");
  if (action) action = String(action).toLowerCase();

  if (action === "toggle") {
    let switchStatus = Shelly.getComponentStatus("switch:" + CONFIG.relay_id);
    action = switchStatus && switchStatus.output ? "off" : "on";
  }

  if (action !== "on" && action !== "off") {
    sendJson(response, 400, {
      ok: false,
      message: "invalid action; expected action=on|off|toggle",
      query: request.query || null,
    });
    return;
  }

  Shelly.call("Switch.Set", { id: CONFIG.relay_id, on: action === "on" }, function (result, errCode, errMsg) {
    if (errCode !== 0) {
      sendJson(response, 500, {
        ok: false,
        message: "relay switch failed",
        error_code: errCode,
        error: errMsg,
      });
      return;
    }

    sendJson(response, 200, {
      ok: true,
      action: action,
      relay_id: CONFIG.relay_id,
      result: result,
      message: action === "on" ? "light turned on" : "light turned off",
    });
  });
});

registerAtCentral();
Timer.set(CONFIG.heartbeat_interval_sec * 1000, true, sendHeartbeat);
print("Endpoint registered at: " + registeredPath);