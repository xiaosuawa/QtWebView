# QtWebView2

<div align="center">
<img src="https://img.shields.io/pypi/v/qtwebview2" alt="PyPI version">
<img src="https://img.shields.io/pypi/l/qtwebview2" alt="License">
<img src="https://img.shields.io/pypi/pyversions/qtwebview2" alt="Python versions">
<img src="https://img.shields.io/pypi/dm/qtwebview2" alt="Downloads">
</div>

| English | [简体中文](https://github.com/xiaosuyyds/QtWebView2/blob/master/README_ZH.md) |

## 📖 Introduction
QtWebView2 is a Python wrapper for embedding Microsoft's WebView2 into a Qt application, complete with a powerful JS bridge. It is built upon QtPy and Python.NET.

**Disclaimer:** This project is currently in a beta stage. The API may change in future updates, but early adopters and feedback are welcome!

## ✨ Features

- 🎸 **Lightweight Integration**: Directly wraps the native WebView2 control using Python.NET, resulting in a minimal increase in your application's package size compared to solutions like `QWebEngineView`.
- 🎻 **Powerful JS Bridge**: Provides a robust JS bridge solution for seamless two-way communication between Python and JavaScript, using modern JS features like `Promise` and `async/await`.
- 🎷 **WSGI Compatible**: Allows the content returned by WSGI to be passed directly to WebView2, passed directly to WebView2, making it easier to pass resources or write.
- 🎺 **Out-of-the-Box**: Comes with rich configuration options and robust error handling, allowing you to get started quickly with minimal setup.
- 🎼 **QtPy Support**: Built on QtPy, making it compatible with both PyQt6 and PySide6.

## 🤔 Quick Comparison

| Feature             |                    QtWebView2 (This Project)                    |                        `pywebview`                         |         `QWebEngineView` (Qt)          |
|:--------------------|:---------------------------------------------------------------:|:----------------------------------------------------------:|:--------------------------------------:|
| **Qt Integration**  |                **Native-like (Layout & Events)**                |         **Pseudo-embedding (Focus/Event Issues)**          |         **True Native Widget**         |
| **Rendering**       |             HWND-based (Airspace issues, but minor)             |                HWND-based (Airspace issues)                | Fully composited (No airspace issues)  |
| **Cross-Platform**  |                        ❌ (Windows Only)                         |                   ✅ (Win, macOS, Linux)                    |         ✅ (Win, macOS, Linux)          |
| **Package Size**    |                           **Minimal**                           | Small, but the middle layer needs to be developed manually |             **Very Large**             |
| **Backend Pattern** |                  **Portless WSGI** / JS Bridge                  |               Local HTTP Server / JS Bridge                |   `QWebChannel` / Local HTTP Server    |
| **Best For...**     | **Lightweight Windows apps where seamless interaction is key.** |          Simple, standalone cross-platform apps.           | Visually complex, large-scale Qt apps. |

## ⬇️ Installation
⚠️ **Note:** This library currently supports the **Windows platform only**.

```bash
python -m pip install qtwebview2
```

Alternatively, you can install from the source:

```bash
git clone https://github.com/xiaosuyyds/QtWebView2.git
cd QtWebView2
python -m pip install .
```

**Important!** The corresponding Qt backend is not installed as a dependency. You need to install your preferred backend (e.g., PySide6 or PyQt6) yourself.

## 🧑‍💻 Usage
Here is a complete example demonstrating the core features.

```python
import sys
from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget
from qtpy.QtCore import Slot, QCoreApplication
from qtwebview2 import QtWebView2Widget, DictJsBridge

# Set an application name for the user data folder
QCoreApplication.setApplicationName("QtWebView2-Demo")

# 1. Initialize the application and window
app = QApplication(sys.argv)
window = QWidget()
window.setWindowTitle("QtWebView2-Demo")
window.setGeometry(100, 100, 800, 600)
layout = QVBoxLayout(window)

# 2. Create an instance of the JS bridge
js_bridge = DictJsBridge()

# 3. Create the WebView2 widget and inject the JS bridge
webview = QtWebView2Widget(parent=window, js_apis=js_bridge)
layout.addWidget(webview)


# 4. (JS -> Python) Define a Python function and expose it to JavaScript
@js_bridge.bind_js_api_func
def get_user_os():
    """This Python function will be callable from JavaScript."""
    print(f"Python function 'get_user_os' was called from JavaScript!")
    return sys.platform


# 5. Define HTML content that includes JavaScript to call the Python function
html_content = """
<!DOCTYPE html>
<html>
<head><title>JS Bridge Test</title></head>
<body style="font-family: sans-serif; text-align: center; background-color: #f0f0f0;">
    <h1>QtWebView2 JS Bridge Demo</h1>
    <button onclick="callPython()">Click me to call Python!</button>
    <p>Result from Python: <b id="result">...</b></p>
    <script>
        async function callPython() {
            try {
                // Use async/await to call the Python function and get the result
                const os = await window.qtwebview2.api.get_user_os();
                document.getElementById('result').textContent = os;
            } catch (e) {
                document.getElementById('result').textContent = 'Error: ' + e;
            }
        }
    </script>
</body>
</html>
"""

webview.load_html(html_content)


# 6. (Python -> JS) Connect to a signal and execute JavaScript when it's emitted
@Slot()
def on_dom_loaded():
    """This function is called when the web page's DOM is fully loaded."""
    print(f"DOM content loaded. Executing JS from Python...")
    # You can also execute JavaScript from Python
    webview.evaluate_js("""(function() {
        const new_element = document.createElement('h2');
        new_element.textContent = 'Hello from Python!';
        document.body.appendChild(new_element);
    })()""")


webview.bridge.domContentLoaded.connect(on_dom_loaded)

window.show()
sys.exit(app.exec())
```

A WSGI Demo(need flask):

```python
import sys
import random
from datetime import datetime

from flask import Flask, jsonify, render_template_string

from qtpy.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton, QFrame
from qtpy.QtCore import Qt
from qtwebview2 import QtWebView2Widget


flask_app = Flask(__name__)

VIRTUAL_HOST = "myapp.local"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            padding: 0; margin: 0; 
            background: #f5f7fa; color: #2c3e50; 
            display: flex; justify-content: center; align-items: center; height: 100vh;
        }
        .container { 
            background: white; width: 80%; max-width: 600px;
            padding: 40px; border-radius: 12px; 
            box-shadow: 0 4px 20px rgba(0,0,0,0.08); 
            text-align: center;
        }
        h1 { margin-top: 0; color: #34495e; }
        .tag { 
            background: #e1f5fe; color: #0288d1; 
            padding: 4px 8px; border-radius: 4px; font-size: 0.9em; font-weight: bold;
        }
        button { 
            padding: 12px 24px; background: #00c853; color: white; 
            border: none; border-radius: 6px; cursor: pointer; font-size: 16px;
            transition: background 0.2s;
        }
        button:hover { background: #00e676; }
        #result-box {
            margin-top: 20px; padding: 15px; background: #263238; color: #80cbc4;
            border-radius: 6px; font-family: monospace; text-align: left; min-height: 60px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🐍 Flask + 🖥️ WebView2</h1>
        <p>This is a running in Qt memory <span class="tag">WSGI App</span></p>
        <p>Server Time: <strong>{{ time }}</strong></p>

        <div style="margin: 30px 0;">
            <button onclick="fetchData()">⚡ Initiate a fetch request</button>
        </div>

        <div id="result-box">// Click the button to get the JSON data...</div>
    </div>

    <script>
        async function fetchData() {
            const box = document.getElementById('result-box');
            box.textContent = "// Loading...";
            try {
                const res = await fetch('/api/random', {method: 'POST'});
                const data = await res.json();
                box.textContent = JSON.stringify(data, null, 2);
            } catch(e) {
                box.textContent = "Error: " + e;
            }
        }
    </script>
</body>
</html>
"""


@flask_app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, time=datetime.now().strftime("%H:%M:%S"))


@flask_app.route('/api/random', methods=['POST'])
def api_random():
    return jsonify({
        "value": random.randint(1000, 9999),
        "source": "Internal Flask Backend",
        "status": "success"
    })


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QtWebView2 WSGI Demo")
        self.resize(1000, 700)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.top_bar = QFrame()
        self.top_bar.setFixedHeight(50)
        self.top_bar.setStyleSheet("""
            QFrame { background-color: #ffffff; border-bottom: 1px solid #e0e0e0; }
            QLabel { color: #333; font-size: 14px; font-weight: bold; }
            QPushButton {
                background-color: transparent; border: 1px solid #ccc; border-radius: 4px;
                padding: 5px 15px; color: #555;
            }
            QPushButton:hover { background-color: #f0f0f0; color: #000; }
        """)

        bar_layout = QHBoxLayout(self.top_bar)
        bar_layout.setContentsMargins(15, 0, 15, 0)

        title_label = QLabel("🚀 QtWebView2 Demo")

        self.status_label = QLabel("🟢 WSGI Server Running")
        self.status_label.setStyleSheet("color: #4caf50; font-size: 12px; font-weight: normal;")

        refresh_btn = QPushButton("Reload")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self.reload_webview)

        bar_layout.addWidget(title_label)
        bar_layout.addSpacing(20)
        bar_layout.addWidget(self.status_label)
        bar_layout.addStretch()
        bar_layout.addWidget(refresh_btn)

        self.webview = QtWebView2Widget(
            parent=self,
            wsgi_app=flask_app,
            wsgi_host_name=VIRTUAL_HOST,
            debug=True,
            url=f"http://{VIRTUAL_HOST}/"
        )

        main_layout.addWidget(self.top_bar)

        main_layout.addWidget(self.webview, 1)

    def reload_webview(self):
        self.webview.reload()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
```

## 📦 Packaging

When packaging your application, ensure the files under `qtwebview2/lib/` are included — they contain the .NET assemblies and native DLLs required at runtime.

| Packager | Notes |
|----------|-------|
| **PyInstaller** | No action needed — a hook is shipped with the package and runs automatically. |
| **Nuitka** | Add `--user-package-configuration-file=nuitka-package.config.yml` with the config below, and `--nofollow-import-to=Microsoft,System` to avoid CLR import issues. |
| **Others** | Copy the `lib/` directory from `qtwebview2` into your distribution alongside the executable. |

<details>
<summary>Nuitka config (nuitka-package.config.yml)</summary>

```yaml
- module-name: 'qtwebview2'
  data-files:
    - dirs:
        - 'lib'
  dlls:
    - from_filenames:
        relative_path: 'lib/runtimes/win-x86/native'
        prefixes:
          - 'WebView2Loader'
      when: 'win32 and arch_x86'
    - from_filenames:
        relative_path: 'lib/runtimes/win-x64/native'
        prefixes:
          - 'WebView2Loader'
      when: 'win32 and arch_amd64'
    - from_filenames:
        relative_path: 'lib/runtimes/win-arm64/native'
        prefixes:
          - 'WebView2Loader'
      when: 'win32 and arch_arm64'
    - from_filenames:
        relative_path: 'lib/x86'
        prefixes:
          - 'WebView2Loader'
      when: 'win32 and arch_x86'
    - from_filenames:
        relative_path: 'lib/x64'
        prefixes:
          - 'WebView2Loader'
      when: 'win32 and arch_amd64'
    - from_filenames:
        relative_path: 'lib/arm64'
        prefixes:
          - 'WebView2Loader'
      when: 'win32 and arch_arm64'
    - from_filenames:
        relative_path: 'lib'
        prefixes:
          - 'Microsoft.'
      when: 'win32'
```
</details>

## License

Copyright (c) 2025-2026 Xiaosu.

Distributed under the terms of the [Mozilla Public License Version 2.0](https://github.com/xiaosuyyds/QtWebView2/blob/master/LICENSE).