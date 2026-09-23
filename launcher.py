"""
launcher.py — wraps app.py for PyInstaller.
Opens the browser automatically, runs Flask in a background thread.
"""
import os
import sys
import threading
import time
import webbrowser

# ── When frozen, resolve paths relative to the .exe ──────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS          # PyInstaller temp extraction folder
    WORK_DIR = os.path.dirname(sys.executable)   # folder where .exe lives
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    WORK_DIR = BASE_DIR

# Change working directory to where the .exe is so user_data/ is created there
os.chdir(WORK_DIR)

# Add BASE_DIR to path so app.py can import its dependencies
sys.path.insert(0, BASE_DIR)

PORT = 5000
URL  = f"http://127.0.0.1:{PORT}"


def run_flask():
    # Import here so it runs inside the thread after sys.path is set
    from app import app
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    print("=" * 50)
    print("  UPC / LP Search Portal")
    print(f"  Starting on {URL}")
    print("  Close this window to stop the app.")
    print("=" * 50)

    # Start Flask in background thread
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    # Give Flask a moment to start then open the browser
    time.sleep(1.5)
    webbrowser.open(URL)

    # Keep the main thread alive (shows the console window)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down.")
