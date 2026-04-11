def build_shelly_unavailable_message(error_text: str) -> str:
    lowered = error_text.lower()
    network_indicators = (
        "no route to host",
        "network is unreachable",
        "timed out",
        "timeout",
        "connection refused",
        "name or service not known",
        "temporary failure in name resolution",
        "shelly-request fehlgeschlagen",
    )
    if any(indicator in lowered for indicator in network_indicators):
        return (
            "Ich kann das Gerät gerade nicht erreichen. "
            "Bitte stelle sicher, dass es Strom hat und im Netzwerk eingebunden ist."
        )
    return "Der Smart-Home-Befehl ist fehlgeschlagen. Bitte prüfe das Zielgerät."
