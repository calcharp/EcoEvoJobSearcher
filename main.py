import socket
import threading
import webbrowser
from datetime import datetime, timezone

from jobboards.db import init_db
from jobboards.geocode import start_geocoder_daemon
from jobboards.scrape.runner import ScrapeState, run_scrape_async
from jobboards.server import create_app, start_watchdog, touch_heartbeat


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    init_db()
    touch_heartbeat()
    start_watchdog()
    start_geocoder_daemon()

    state = ScrapeState()
    app = create_app(state)
    port = find_free_port()

    # Show "starting" before the background thread sets running=True
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    state.update(phase="starting", message="Starting update…", started_at=started_at)
    run_scrape_async(state)

    url = f"http://127.0.0.1:{port}/"
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    print(f"Job Boards running at {url}")
    print("Close the browser tab to exit.")
    app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
