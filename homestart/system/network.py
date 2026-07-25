"""Pure network parsing and interface-selection helpers."""

import re


def network_device_totals(content):
    received = transmitted = 0
    for line in str(content or "").splitlines()[2:]:
        if ":" not in line:
            continue
        interface, values = line.split(":", 1)
        if interface.strip() == "lo":
            continue
        fields = values.split()
        if len(fields) >= 9:
            received += int(fields[0])
            transmitted += int(fields[8])
    return received, transmitted


def parse_ss_tcp_counters(output):
    connections = []
    current = None

    def finish(entry):
        if not entry:
            return
        combined = f"{entry['header']} {entry['details']}"
        pids = re.findall(r"\bpid=(\d+)", entry["header"])
        fields = entry["header"].split()
        if not pids or len(fields) < 5:
            return
        received = re.search(r"\bbytes_received:(\d+)", combined)
        sent = re.search(r"\bbytes_sent:(\d+)", combined)
        if not received and not sent:
            return
        process = re.search(r'\(\("([^"]+)"', entry["header"])
        connections.append({
            "key": f"{pids[0]}:{fields[3]}>{fields[4]}",
            "pid": int(pids[0]),
            "process": process.group(1) if process else "",
            "local": fields[3],
            "peer": fields[4],
            "rx_total": int(received.group(1)) if received else 0,
            "tx_total": int(sent.group(1)) if sent else 0,
            "owner_count": len(set(pids)),
        })

    for raw_line in str(output or "").splitlines():
        if not raw_line.strip():
            continue
        if raw_line[:1].isspace():
            if current:
                current["details"] += f" {raw_line.strip()}"
            continue
        finish(current)
        current = {"header": raw_line.strip(), "details": ""}
    finish(current)
    return connections


def endpoint_address(endpoint):
    value = str(endpoint or "")
    if value.startswith("[") and "]:" in value:
        value = value[1:value.index("]:")]
    elif ":" in value:
        value = value.rsplit(":", 1)[0]
    if value.startswith("::ffff:"):
        value = value[7:]
    return value


def parse_udev_properties(content):
    properties = {}
    for line in str(content or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            properties[key] = value
    return properties


def choose_monitor_interface(items, configured="auto", route_names=None):
    by_name = {item["name"]: item for item in items}
    if configured and configured != "auto" and configured in by_name:
        return configured
    route_names = route_names or []
    for require_connected in (True, False):
        for name in route_names:
            item = by_name.get(name)
            if item and (
                not require_connected
                or item.get("carrier")
                or str(item.get("state", "")).lower() == "up"
            ):
                return name
    for key in ("carrier", "state"):
        for item in items:
            active = (
                item.get(key)
                if key == "carrier"
                else str(item.get(key, "")).lower() == "up"
            )
            if active:
                return item["name"]
    return items[0]["name"] if items else ""
