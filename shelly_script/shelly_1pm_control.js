/*
 * Generic Shelly 1PM script for reusable light-control endpoint.
 * Endpoint: GET /script/light-control?action=on|off
 */

let ENDPOINT_PATH = "/script/light-control";
let RELAY_ID = 0;

function sendJson(response, code, payload) {
  response.code = code;
  response.headers = [["Content-Type", "application/json"]];
  response.body = JSON.stringify(payload);
  response.send();
}

HTTPServer.registerEndpoint(ENDPOINT_PATH, function (request, response) {
  let action = null;
  if (request.query && request.query.action) {
    action = String(request.query.action).toLowerCase();
  }

  if (action !== "on" && action !== "off") {
    sendJson(response, 400, {
      ok: false,
      message: "invalid action; expected action=on|off",
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
          error: errMsg,
        });
        return;
      }

      sendJson(response, 200, {
        ok: true,
        action: action,
        relay_id: RELAY_ID,
        ison: result && result.output,
        message: action === "on" ? "light turned on" : "light turned off",
      });
    }
  );
});

print("Shelly generic light endpoint active at " + ENDPOINT_PATH);
