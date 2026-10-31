import os
import json
import time
import socket
import hashlib
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from fritzconnection import FritzConnection
from fritzconnection.lib.fritzstatus import FritzStatus


# Configuration
FRITZ_HOST = os.getenv("FRITZ_HOST", "192.168.178.1")
FRITZ_USER = os.getenv("FRITZ_USER", "")
FRITZ_PASSWORD = os.getenv("FRITZ_PASSWORD", "")

SYSLOG_HOST = os.getenv("SYSLOG_HOST", "127.0.0.1")
SYSLOG_PORT = int(os.getenv("SYSLOG_PORT", "514"))

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOCAL_TZ = ZoneInfo(os.getenv("TZ", "Europe/Berlin"))

STATE_FILE = Path("/data/last_logs.json")
MAX_HISTORY = 1000


# Logging
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

log = logging.getLogger("fritzlog")


# State management
def load_state():
    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not load state: %s", exc)
        return []


def save_state(history):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(history[-MAX_HISTORY:], file)

    temp_file.replace(STATE_FILE)


# Event fingerprint
def event_fingerprint(event):
    raw = "|".join(
        str(value)
        for value in (
            getattr(event, "id", ""),
            getattr(event, "group", ""),
            getattr(event, "date", ""),
            getattr(event, "time", ""),
            getattr(event, "msg", "")
        )
    )

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# Syslog
def send_syslog(sock, event):
    event_time = event.datetime

    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=LOCAL_TZ)
    else:
        event_time = event_time.astimezone(LOCAL_TZ)

    timestamp = event_time.isoformat(timespec="seconds")
    message = str(event.msg).replace("\r", " ").replace("\n", " ")

    syslog_message = (
        f"<14>1 {timestamp} fritz.box fritzlog - - - {message}"
    )

    sock.sendto(
        syslog_message.encode("utf-8"),
        (SYSLOG_HOST, SYSLOG_PORT)
    )


# Main
def main():
    if not FRITZ_USER or not FRITZ_PASSWORD:
        raise RuntimeError(
            "FRITZ_USER and FRITZ_PASSWORD are required"
        )

    if POLL_INTERVAL < 1:
        raise ValueError("POLL_INTERVAL must be at least 1")

    log.info("Starting FRITZ!Box logger")
    log.info("Router: %s", FRITZ_HOST)
    log.info("Syslog: %s:%s/UDP", SYSLOG_HOST, SYSLOG_PORT)
    log.info("Polling interval: %s seconds", POLL_INTERVAL)

    history = load_state()
    history_set = set(history)

    log.info("Loaded %s known event fingerprints", len(history))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    fc = None
    fritz_status = None

    try:
        while True:
            try:
                if fc is None:
                    log.info("Connecting to FRITZ!Box...")

                    fc = FritzConnection(
                        address=FRITZ_HOST,
                        user=FRITZ_USER,
                        password=FRITZ_PASSWORD
                    )

                    fritz_status = FritzStatus(fc)

                    log.info("Connected to FRITZ!Box")

                events = list(
                    fritz_status.get_avm_device_log()
                )

                events.sort(key=lambda event: event.datetime)

                new_count = 0

                for event in events:
                    fingerprint = event_fingerprint(event)

                    if fingerprint in history_set:
                        continue

                    send_syslog(sock, event)

                    history.append(fingerprint)
                    history_set.add(fingerprint)

                    if len(history) > MAX_HISTORY:
                        history = history[-MAX_HISTORY:]
                        history_set = set(history)

                    save_state(history)
                    new_count += 1

                if new_count:
                    log.info("Forwarded %s new events", new_count)
                else:
                    log.debug("No new events")

            except Exception:
                log.exception("Error while collecting FRITZ!Box logs")
                fc = None
                fritz_status = None

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("Stopping")

    finally:
        sock.close()


if __name__ == "__main__":
    main()
