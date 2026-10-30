"""Entry point: python3 -m web.main

Opens the browser after a short delay unless RSC_NO_BROWSER=1.
"""

import os
import threading
import webbrowser

from web.app import create_app

HOST = "127.0.0.1"
PORT = 8000


def _open_browser_later(url, delay=1.0):
    def opener():
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Timer(delay, opener).start()


def main():
    app = create_app()
    url = f"http://{HOST}:{PORT}"
    print(f"[*] RSC web dashboard -> {url}")

    if not os.environ.get("RSC_NO_BROWSER"):
        _open_browser_later(url)

    app.run(host=HOST, port=PORT, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
