# QtWebView2

<div align="center">
<img src="https://img.shields.io/pypi/v/qtwebview2" alt="PyPI version">
<img src="https://img.shields.io/pypi/l/qtwebview2" alt="License">
<img src="https://img.shields.io/pypi/pyversions/qtwebview2" alt="Python versions">
<img src="https://img.shields.io/pypi/dm/qtwebview2" alt="Downloads">
</div>

| [English](https://github.com/xiaosuyyds/QtWebView2/blob/master/README.md) | 简体中文 |

## 📖 介绍

QtWebView2 是一个用于将微软的 WebView2 嵌入到 Qt 应用程序中的 Python 包装器，并配备了一个功能强大的 JS 桥。它基于 QtPy 和
Python.NET 构建。

**请注意：** 本项目目前处于 Beta 阶段。API 可能会在未来的更新中发生变化，但我们非常欢迎早期使用者和反馈！

## ✨ 特性

- 🎸 **轻量级集成**: 通过 Python.NET 直接包装原生的 WebView2 控件，与 `QWebEngineView` 等方案相比，只会少量增加您应用程序的打包体积。
- 🎻 **强大的 JS 桥**: 提供了一个健壮的 JS 桥接方案，使用 `Promise` 和 `async/await` 等现代 JS 特性，以实现 Python 和
  JavaScript 之间的无缝双向通信。
- 🎷 **WSGI兼容**: 允许直接将WSGI返回的内容传递给 WebView2，让资源传递或是编写都更加轻松。
- 🎺 **开箱即用**: 提供了丰富的配置选项和稳健的错误处理，让您可以用最少的配置快速上手。
- 🎼 **QtPy 支持**: 基于 QtPy 构建，使其同时兼容 PyQt6 和 PySide6。

## 🤔 快速对比

| 特性         |     QtWebView2 (本项目)      |      `pywebview`      |    `QWebEngineView` (Qt)    |
|:-----------|:-------------------------:|:---------------------:|:---------------------------:|
| **Qt 集成度** |      **原生级 (布局与事件)**      |   **伪嵌入 (焦点/事件问题)**   |         **真·原生控件**          |
| **渲染方式**   |     基于 HWND (存在空域问题)      |   基于 HWND (存在空域问题)    |       完全成分合成 (无空域问题)        |
| **跨平台性**   |      ❌ (仅限 Windows)       | ✅ (Win, macOS, Linux) |    ✅ (Win, macOS, Linux)    |
| **包体积增加**  |          **最小**           |     较小，但需手动开发中间层      |           **巨大**            |
| **后端架构模式** |    **无端口 WSGI** / JS 桥    |  本地 HTTP 服务器 / JS 桥   | `QWebChannel` / 本地 HTTP 服务器 |
| **最适用场景**  | **注重无缝交互的轻量级 Windows 应用** |    简单的、窗口独立的跨平台应用     |       视觉效果复杂的大型 Qt 应用       |

## ⬇️ 安装

⚠️ **注意：** 本库目前**仅支持 Windows 平台**。

```bash
python -m pip install qtwebview2
```

或者，您也可以从源码安装：

```bash
git clone https://github.com/xiaosuyyds/QtWebView2.git
cd QtWebView2
python -m pip install .
```

**重要！** 相关的 Qt 后端不会作为依赖被安装。您需要自行安装您偏好的后端（例如 PySide6 或 PyQt6）。

## 🧑‍💻 使用方法

这里是一个完整的示例，演示了其核心功能。

```python
import sys
from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget
from qtpy.QtCore import Slot, QCoreApplication
from qtwebview2 import QtWebView2Widget, DictJsBridge

# 设置一个应用名称，以便用户数据文件夹路径保持稳定
QCoreApplication.setApplicationName("QtWebView2-Demo")

# 1. 初始化应用和窗口
app = QApplication(sys.argv)
window = QWidget()
window.setWindowTitle("QtWebView2-Demo")
window.setGeometry(100, 100, 800, 600)
layout = QVBoxLayout(window)

# 2. 创建 JS 桥接实例
js_bridge = DictJsBridge()

# 3. 创建 WebView2 控件并注入 JS 桥
webview = QtWebView2Widget(parent=window, js_apis=js_bridge)
layout.addWidget(webview)


# 4. (JS -> Python) 定义一个Python函数，并暴露给JavaScript
@js_bridge.bind_js_api_func
def get_user_os():
    """这个Python函数将可以从JavaScript中调用。"""
    print(f"Python函数 'get_user_os' 被JavaScript调用了！")
    return sys.platform


# 5. 定义包含调用Python的JavaScript代码的HTML内容
html_content = """
<!DOCTYPE html>
<html>
<head><title>JS Bridge Test</title></head>
<body style="font-family: sans-serif; text-align: center; background-color: #f0f0f0;">
    <h1>QtWebView2 JS Bridge Demo</h1>
    <button onclick="callPython()">点我调用Python！</button>
    <p>来自Python的结果: <b id="result">...</b></p>
    <script>
        async function callPython() {
            try {
                // 使用 async/await 调用Python函数并获取结果
                const os = await window.qtwebview2.api.get_user_os();
                document.getElementById('result').textContent = os;
            } catch (e) {
                document.getElementById('result').textContent = '错误: ' + e;
            }
        }
    </script>
</body>
</html>
"""

webview.load_html(html_content)


# 6. (Python -> JS) 连接到一个信号，并在信号触发时执行JavaScript
@Slot()
def on_dom_loaded():
    """当网页的DOM完全加载后，此函数会被调用。"""
    print(f"DOM内容已加载。正在从Python执行JS...")
    # 你也可以从Python执行JavaScript
    webview.evaluate_js("""(function() {
        const new_element = document.createElement('h2');
        new_element.textContent = '来自Python的问候！';
        document.body.appendChild(new_element);
    })()""")


# 使用 `domContentLoaded` 信号在加载时进行交互
webview.bridge.domContentLoaded.connect(on_dom_loaded)

window.show()
sys.exit(app.exec())
```

一个 WSGI 示例（需要Flask）：

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

## 📦 打包

在打包你的应用时，请确保 `qtwebview2/lib/` 下的文件被一并包含——它们包含了运行时所需的 .NET 程序集和原生 DLL。

| 打包工具 | 说明 |
|----------|------|
| **PyInstaller** | 无需额外操作——包内已附带 hook，会自动生效。 |
| **Nuitka** | 添加 `--user-package-configuration-file=nuitka-package.config.yml`（配置内容见下方），并添加 `--nofollow-import-to=Microsoft,System` 以避免 CLR 导入问题。 |
| **其他** | 确保 `lib/` 目录在 `qtwebview2` 包下保持原有相对位置，以便运行时能正确定位 DLL。具体做法请参考对应打包工具的文档。 |

<details>
<summary>Nuitka 配置文件 (nuitka-package.config.yml)</summary>

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

## 许可证

版权所有 (c) 2025-2026 Xiaosu。

根据 [Mozilla Public License Version 2.0](https://github.com/xiaosuyyds/QtWebView2/blob/master/LICENSE) 的条款分发。
