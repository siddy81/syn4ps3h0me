from app.error_messages import build_shelly_unavailable_message


def test_build_shelly_unavailable_message_for_network_errors():
    msg = build_shelly_unavailable_message("Shelly-Request fehlgeschlagen: <urlopen error [Errno 113] No route to host>")
    assert "Strom" in msg
    assert "Netzwerk" in msg


def test_build_shelly_unavailable_message_for_other_errors():
    msg = build_shelly_unavailable_message("HTTP 500 internal error")
    assert "fehlgeschlagen" in msg
