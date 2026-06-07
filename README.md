# QtWebView

<div align="center">
<img src="https://img.shields.io/pypi/v/qtwebview2" alt="PyPI version">
<img src="https://img.shields.io/pypi/l/qtwebview2" alt="License">
<img src="https://img.shields.io/pypi/pyversions/qtwebview2" alt="Python versions">
</div>

| English | [简体中文](README_ZH.md) |

---

## ⚡ v0.6.0 Rewrite

v0.6.0 replaces the old **pythonnet + .NET CLR + WebView2 WinForms** backend with **[wryview](https://github.com/xiaosuawa/wryview)**, a Rust-powered binding for [wry](https://github.com/tauri-apps/wry) (the WebView engine used by [Tauri](https://tauri.app)).

This brings **cross-platform support** (Windows, macOS, Linux), **faster startup** (no .NET CLR), and access to the **wry API** (cookies, devtools, custom protocols, etc.).

See [Migration Guide](#-migration-from-v05x) below if upgrading from v0.5.x.

## 📖 Introduction

QtWebView embeds a wry WebView as a native child window inside any Qt (PySide/PyQt) widget. Built on QtPy and wryview.

## ✨ Features

- **Cross-Platform** — Windows (WebView2), macOS (WKWebView), Linux (WebKitGTK). Same API everywhere.
- **Qt-Native Embedding** — True QWidget via native child window, not a pseudo-overlay.
- **JS Bridge** — Two-way Python ↔ JavaScript communication with async/await support.
- **WSGI Compatible** — Run Flask, Bottle, Django inside the webview via custom protocol (no TCP server).
- **Persistent Cache** — Automatic user data folder for fast warm starts. Incognito mode available.
- **Wry API** — Cookies, devtools, zoom, print, drag-drop, custom headers, and more.
- **Lazy Loading** — Window appears instantly, WebView loads in background.

## ⬇️ Installation

```bash
pip install qtwebview2

# You also need a Qt backend:
pip install pyside6    # or pyqt6
```

## 🧑‍💻 Usage

### Basic

```python
import sys
from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget
from qtwebview2 import QtWebViewWidget

app = QApplication(sys.argv)
win = QWidget()
win.setWindowTitle("QtWebView")
win.resize(800, 600)
layout = QVBoxLayout(win)

webview = QtWebViewWidget(url="https://example.com", parent=win)
layout.addWidget(webview)

win.show()
sys.exit(app.exec())
```

### JS Bridge — Python ↔ JavaScript

Expose Python functions to JavaScript with `DictJsBridge`. JS calls Python via
`window.qtwebview.api.funcName()` — with full `Promise` / `async` / `await` support.

```python
import sys
from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget
from qtpy.QtCore import Slot
from qtwebview2 import QtWebViewWidget, DictJsBridge

app = QApplication(sys.argv)
win = QWidget()
win.setWindowTitle("JS Bridge Demo")
win.resize(800, 600)
layout = QVBoxLayout(win)

# 1. Create the JS bridge and register Python functions
js_bridge = DictJsBridge()

@js_bridge.bind_js_api_func
def get_system_info():
    """Callable from JS: await window.qtwebview.api.get_system_info()"""
    import platform
    return {
        "os": platform.system(),
        "python": platform.python_version(),
        "arch": platform.machine(),
    }

@js_bridge.bind_js_api_func
def greet(name: str):
    """Callable from JS: await window.qtwebview.api.greet('World')"""
    return f"Hello, {name}! — from Python"

# 2. Create the webview with the bridge
webview = QtWebViewWidget(parent=win, js_apis=js_bridge)
layout.addWidget(webview)

# 3. Load HTML that uses the bridge
webview.load_html("""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>JS Bridge</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 40px;">
    <h1>🐍 Python ↔ JavaScript</h1>
    <button onclick="callPython()" style="padding:12px 24px; font-size:16px;">
        Call Python
    </button>
    <pre id="output" style="margin-top:20px; text-align:left; background:#1e1e1e;
        color:#4ec9b0; padding:16px; border-radius:8px; min-height:80px;">
// click the button...
    </pre>
    <script>
        async function callPython() {
            const out = document.getElementById('output');
            out.textContent = '// calling...';
            try {
                const info = await window.qtwebview.api.get_system_info();
                const msg  = await window.qtwebview.api.greet('Qt');
                out.textContent = JSON.stringify(info, null, 2) + '\n\n' + msg;
            } catch (e) {
                out.textContent = 'Error: ' + e;
            }
        }
    </script>
</body>
</html>
""")

# 4. Python → JS: execute JavaScript when the page loads
@Slot(str, str)
def on_page_loaded(evt, url):
    if evt == "Finished":
        webview.eval_js(
            'document.body.style.background = "linear-gradient(135deg, #667eea, #764ba2)"'
        )

webview.signals.page_loaded.connect(on_page_loaded)

win.show()
sys.exit(app.exec())
```

### WSGI — Flask / Bottle / Django

Run your WSGI app inside the webview. Requests are served via custom protocol
(`qtwebview://` scheme) — no TCP port, zero network overhead. Or switch to
localhost mode with `wsgi_scheme="localhost"`.

```python
import sys
import random
from datetime import datetime

from flask import Flask, jsonify, render_template_string

from qtpy.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout,
                             QWidget, QLabel, QPushButton, QFrame)
from qtpy.QtCore import Qt
from qtwebview2 import QtWebViewWidget

# ── Flask app ───────────────────────────────────────────────────────
flask_app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                         Helvetica, Arial, sans-serif;
            background: #f5f7fa; color: #2c3e50;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh;
        }
        .card {
            background: #fff; width: 90%; max-width: 520px;
            padding: 40px; border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08); text-align: center;
        }
        h1 { color: #34495e; margin-bottom: 8px; }
        .tag {
            display: inline-block; background: #e1f5fe; color: #0288d1;
            padding: 3px 8px; border-radius: 4px; font-size: 0.85em;
            font-weight: 600; margin-bottom: 20px;
        }
        button {
            padding: 10px 24px; background: #00c853; color: #fff;
            border: none; border-radius: 6px; cursor: pointer; font-size: 15px;
            transition: background 0.2s; margin-top: 16px;
        }
        button:hover { background: #00e676; }
        #result-box {
            margin-top: 20px; padding: 16px; background: #263238;
            color: #80cbc4; border-radius: 6px; font-family: "Fira Code",
            "Cascadia Code", Consolas, monospace; text-align: left;
            min-height: 60px; white-space: pre-wrap; font-size: 13px;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>🐍 Flask + 🖥️ QtWebView</h1>
        <span class="tag">WSGI · Custom Protocol</span>
        <p>Server Time: <strong>{{ time }}</strong></p>
        <button onclick="fetchData()">⚡ Fetch JSON from Flask</button>
        <div id="result-box">// Click the button...</div>
    </div>
    <script>
        async function fetchData() {
            const box = document.getElementById('result-box');
            box.textContent = '// Loading...';
            try {
                const res = await fetch('/api/random', { method: 'POST' });
                const data = await res.json();
                box.textContent = JSON.stringify(data, null, 2);
            } catch (e) {
                box.textContent = 'Error: ' + e;
            }
        }
    </script>
</body>
</html>
"""

@flask_app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE,
                                  time=datetime.now().strftime("%H:%M:%S"))

@flask_app.route("/api/random", methods=["POST"])
def api_random():
    return jsonify({
        "value": random.randint(1000, 9999),
        "source": "Flask Backend",
        "status": "success",
    })


# ── Qt Window ───────────────────────────────────────────────────────
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QtWebView WSGI Demo")
        self.resize(900, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet("""
            QFrame { background: #fff; border-bottom: 1px solid #e0e0e0; }
            QLabel { color: #333; font-size: 13px; font-weight: 600; }
            QPushButton {
                background: transparent; border: 1px solid #ccc;
                border-radius: 4px; padding: 4px 14px; color: #555;
            }
            QPushButton:hover { background: #f0f0f0; color: #000; }
        """)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 0, 12, 0)
        bar_layout.addWidget(QLabel("🚀 QtWebView WSGI Demo"))
        bar_layout.addStretch()
        reload_btn = QPushButton("Reload")
        reload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reload_btn.clicked.connect(self._reload)
        bar_layout.addWidget(reload_btn)
        layout.addWidget(bar)

        # WebView — WSGI served via qtwebview:// scheme
        self.webview = QtWebViewWidget(
            parent=self, wsgi_app=flask_app, debug=True
        )
        layout.addWidget(self.webview, 1)

    def _reload(self):
        self.webview.reload()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
```

## 📊 Quick Comparison

|                    | QtWebView (v0.6.0+)          | pywebview       | QWebEngineView  |
|--------------------|------------------------------|-----------------|-----------------|
| **Qt Integration** | ✅ Native QWidget             | ⚠️ Pseudo-embed | ✅ Native        |
| **Cross-Platform** | ✅ Win/Mac/Linux              | ✅               | ✅               |
| **Package Size**   | ✅ Small (wryview .pyd)       | Small           | ❌ Large (~80MB) |
| **WSGI**           | ✅ Custom protocol (portless) | Local HTTP      | QWebChannel     |
| **JS Bridge**      | ✅ Promise/async              | ✅               | ⚠️ Complex      |
| **Startup**        | ~1.5s                        | ~1~3s           | ~2-3s           |

## 🔄 Migration from v0.5.x

```python
# Old (v0.5.x)                            → New (v0.6.0)
from qtwebview2 import QtWebView2Widget    from qtwebview2 import QtWebViewWidget
webview = QtWebView2Widget(url=...)        webview = QtWebViewWidget(url=...)

# Parameters with different names:
# handle_new_window=True/False   → new_window_handler=lambda url: "allow"|"deny"
# wsgi_host_name="myapp.local"   → wsgi_scheme="qtwebview"
# browser_executable_folder=...  → (not supported by wry)
# fullscreen_support=True        → (not yet implemented)
# no_local_storage=True          → (removed, use incognito=True)

# Removed parameters (no equivalent):
# context_menus, init_settings_hook

# New parameters in v0.6.0:
# html, headers, navigation_handler, incognito, autoplay,
# javascript_enabled, hotkeys_zoom, drag_drop_handler
```

## 📦 API Overview

```python
webview = QtWebViewWidget(
    url="https://example.com",           # initial URL
    html="<h1>Hello</h1>",               # or initial HTML
    headers={"Authorization": "Bearer"},  # custom HTTP headers
    user_agent="CustomAgent/1.0",
    debug=True,                            # DevTools on
    transparent=False,
    background_color="#1e1e1e",
    navigation_handler=lambda url: True,   # return False to block
    new_window_handler=lambda url: "allow",
    lazyload=True,                         # defer to showEvent
    incognito=False,
    user_data_folder="/path/to/cache",
    wsgi_app=flask_app,
    wsgi_scheme="qtwebview",
    autoplay=False,
    javascript_enabled=True,
    hotkeys_zoom=True,
    drag_drop_handler=lambda evt, paths, pos: True,
)

webview.load_url(url)                     # Navigate
webview.load_url_with_headers(url, hdrs)  # Navigate with headers
webview.load_html(html)                   # Load HTML
webview.reload()                          # Reload
webview.url()                             # Get current URL
webview.eval_js(script)                   # Execute JS
webview.evaluate_js(script, callback)     # Execute JS with callback
webview.cookies()                         # Get all cookies
webview.cookies_for_url(url)              # Get cookies for a URL
webview.set_cookie(name, value)           # Set cookie
webview.delete_cookie(name, url)          # Delete cookie
webview.open_devtools()                   # Open DevTools
webview.close_devtools()                  # Close DevTools
webview.zoom(1.5)                         # Zoom 150%
webview.print()                           # Print page
webview.focus()                           # Focus webview
webview.set_background_color(r, g, b, a)  # Set background color
webview.clear_all_browsing_data()         # Clear cache

# Signals
webview.signals.page_loaded.connect(lambda evt, url: ...)
webview.signals.title_changed.connect(lambda title: ...)
webview.signals.navigation_requested.connect(lambda url: ...)
webview.signals.new_window_requested.connect(lambda url: ...)
webview.signals.web_message_received.connect(lambda msg: ...)
webview.signals.initialization_done.connect(lambda: ...)
```

## License

Copyright (c) 2025-2026 Xiaosu.

Distributed under the terms of the [Mozilla Public License Version 2.0](https://github.com/xiaosuawa/QtWebView/blob/master/LICENSE).
