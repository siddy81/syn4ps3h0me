/*
 * Generic Shelly 1PM script for reusable light-control endpoint.
 * Endpoint: GET /script/light-control?action=on|off
 */
let ENDPOINT_NAME = "light-control";
let RELAY_ID = 0;

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

let registeredPath = HTTPServer.registerEndpoint(ENDPOINT_NAME, function (request, response) {
  let action = getQueryParam(request.query, "action");
  if (action) action = String(action).toLowerCase();

  if (action !== "on" && action !== "off") {
    sendJson(response, 400, {
      ok: false,
      message: "invalid action; expected action=on|off",
      query: request.query || null
    });
    return;
  }

  Shelly.call(
      "Switch.Set",
      { id: RELAY_ID, on: action === "on" },
      function (result, errCode, errMsg) {
        if (errCode !== 0) {
          sendJson(response, 500, {
            ok: false,
            message: "relay switch failed",
            error_code: errCode,
            error: errMsg
          });
          return;
        }

        sendJson(response, 200, {
          ok: true,
          action: action,
          relay_id: RELAY_ID,
          result: result,
          message: action === "on" ? "light turned on" : "light turned off"
        });
      }
  );
});

print("Endpoint registered at: " + registeredPath);