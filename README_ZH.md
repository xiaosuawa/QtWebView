# QtWebView

<div align="center">
<img src="https://img.shields.io/pypi/v/qtwebview2" alt="PyPI version">
<img src="https://img.shields.io/pypi/l/qtwebview2" alt="License">
<img src="https://img.shields.io/pypi/pyversions/qtwebview2" alt="Python versions">
</div>

| [English](README.md) | 简体中文 |

---

## ⚡ v0.6.0 重构

v0.6.0 将旧的 **pythonnet + .NET CLR + WebView2 WinForms** 后端替换为 **[wryview](https://github.com/xiaosuawa/wryview)**（[wry](https://github.com/tauri-apps/wry) 的 Rust 绑定，[Tauri](https://tauri.app) 的 WebView 引擎）。

带来 **跨平台支持**（Windows、macOS）、**更快的启动速度**（去掉了 .NET CLR）、以及 **wry API**（Cookie、DevTools、自定义协议等）。Linux 暂不支持（欢迎贡献 PR！）。

从 v0.5.x 升级请参考[迁移指南](#-从-v05x-迁移)。

## 📖 简介

QtWebView 将 wry WebView 作为原生子窗口嵌入任何 Qt（PySide/PyQt）widget。基于 QtPy 和 wryview。

## ✨ 特性

- **跨平台** — Windows（WebView2）、macOS（WKWebView），统一 API。Linux 暂不支持。
- **Qt 原生嵌入** — 真正的 QWidget 子窗口，非伪覆盖层。
- **JS Bridge** — Python ↔ JavaScript 双向通信，支持 async/await。
- **WSGI 兼容** — 在 WebView 中运行 Flask、Bottle、Django，通过自定义协议（无需 TCP 端口）。
- **持久缓存** — 自动用户数据目录，实现快速热启动。支持无痕模式。
- **Wry API** — Cookie、DevTools、缩放、打印、拖放、自定义 header 等。
- **懒加载** — 窗口立即可见，WebView 后台加载。

## ⬇️ 安装

```bash
pip install qtwebview2

# 还需要 Qt 后端：
pip install pyside6    # 或 pyqt6
```

## 🧑‍💻 使用示例

### 基础用法

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

<details>
<summary>### JS Bridge — Python ↔ JavaScript 双向通信</summary>

通过 `DictJsBridge` 将 Python 函数暴露给 JavaScript。JS 端使用
`window.qtwebview.api.funcName()` 调用，完全支持 `Promise` / `async` / `await`。

```python
import sys
from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget
from qtpy.QtCore import Slot, QCoreApplication
from qtwebview2 import QtWebViewWidget, DictJsBridge

# 设置一个应用名称，以便用户数据文件夹路径保持稳定
QCoreApplication.setApplicationName("QtWebView-Demo")

# 1. 初始化应用和窗口
app = QApplication(sys.argv)
win = QWidget()
win.setWindowTitle("JS Bridge 示例")
win.resize(800, 600)
layout = QVBoxLayout(win)

# 2. 创建 JS 桥接实例
js_bridge = DictJsBridge()

# 3. 创建 WebView2 控件并注入 JS 桥
webview = QtWebViewWidget(js_apis=js_bridge, debug=True)
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
    <h1>QtWebView JS Bridge Demo</h1>
    <button onclick="callPython()">点我调用Python！</button>
    <p>来自Python的结果: <b id="result">...</b></p>
    <script>
        async function callPython() {
            try {
                // 使用 async/await 调用Python函数并获取结果
                const os = await window.qtwebview.api.get_user_os();
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


# 6. Python → JS: 页面加载完成后执行 JavaScript
@Slot(str, str)
def on_page_loaded(evt, url):
    if evt == "Finished":
        webview.evaluate_js("""(function() {
            const new_element = document.createElement('h2');
            new_element.textContent = '来自Python的问候！';
            document.body.appendChild(new_element);
        })()""")


webview.signals.page_loaded.connect(on_page_loaded)

win.show()
sys.exit(app.exec())
```

</details>

<details>
<summary>### WSGI — 运行 Flask / Bottle / Django</summary>

在 WebView 中运行 WSGI 应用，通过自定义协议（`qtwebview://` scheme）提供服务
—— 无需 TCP 端口，零网络开销。也可以使用 `wsgi_scheme="localhost"` 切换到本地 HTTP 模式。

```python
import sys
import random
from datetime import datetime

from flask import Flask, jsonify, render_template_string

from qtpy.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout,
                             QWidget, QLabel, QPushButton, QFrame)
from qtpy.QtCore import Qt
from qtwebview2 import QtWebViewWidget

# ── Flask 应用 ───────────────────────────────────────────────────────
flask_app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
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
        <span class="tag">WSGI · 自定义协议</span>
        <p>服务器时间: <strong>{{ time }}</strong></p>
        <button onclick="fetchData()">⚡ 从 Flask 获取 JSON</button>
        <div id="result-box">// 点击按钮...</div>
    </div>
    <script>
        async function fetchData() {
            const box = document.getElementById('result-box');
            box.textContent = '// 加载中...';
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
        "source": "Flask 后端",
        "status": "success",
    })


# ── Qt 窗口 ─────────────────────────────────────────────────────────
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QtWebView WSGI 示例")
        self.resize(900, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 工具栏
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
        bar_layout.addWidget(QLabel("🚀 QtWebView WSGI 示例"))
        bar_layout.addStretch()
        reload_btn = QPushButton("重新加载")
        reload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reload_btn.clicked.connect(self._reload)
        bar_layout.addWidget(reload_btn)
        layout.addWidget(bar)

        # WebView —— 通过 qtwebview:// scheme 提供 WSGI 服务
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

</details>

## ⚠️ 系统托盘 / 隐藏与恢复

默认模式下 `QtWebViewWidget` 使用独立的锚点窗口（`native_child=False`）
—— WebView **不受**父窗口 hide/show 影响，托盘应用可直接使用。

如果通过 `native_child=True` 切回旧的直接子窗口模式，WebView 会随父窗口
HWND 一起销毁：

```python
# 仅 native_child=True 时需要：
def closeEvent(self, event):
    event.ignore()   # 不销毁原生窗口
    self.hide()      # 仅隐藏——WebView 保持存活
```

## 📊 快速对比

|               | QtWebView (v0.6.0+) | pywebview | QWebEngineView |
|---------------|---------------------|-----------|----------------|
| **Qt 集成**     | ✅ 原生 QWidget        | ⚠️ 需自行嵌入  | ✅ 原生           |
| **跨平台**       | ✅ Win/Mac           | ✅         | ✅              |
| **包体积**       | ✅ 小巧（wryview <1MB）  | 小巧        | ❌ 庞大（>160MB）   |
| **WSGI**      | ✅ 自定义协议（无需端口）       | 本地 HTTP   | QWebChannel    |
| **JS Bridge** | ✅ Promise/async     | ✅         | ⚠️ 复杂          |
| **启动速度**      | ~1-2s               | ~1-3s     | ~2-3s          |
| **半透明叠加**     | ❌ 系统限制              | ❌ 系统限制    | ✅ 原生混合         |

> **空域问题（Airspace）**：Windows 上 HWND 子窗口与 Qt 原生渲染分属不同渲染管线。
> 不透明 Qt 组件放在 WebView 之上可以正常显示，但**半透明**组件只会与下方 Qt 窗口混合，
> **不会**与 WebView 内容混合。这是 Win32 窗口系统的限制，
> QWebEngineView 因使用 Qt 原生渲染管线无此问题。

## 🔄 从 v0.5.x 迁移

```python
# 旧版 (v0.5.x)                          → 新版 (v0.6.0)
from qtwebview2 import QtWebView2Widget    from qtwebview2 import QtWebViewWidget
webview = QtWebView2Widget(url=...)        webview = QtWebViewWidget(url=...)

# 参数名称变更：
# handle_new_window=True/False   → new_window_handler=lambda url: "allow"|"deny"
# wsgi_host_name="myapp.local"   → wsgi_scheme="qtwebview"
# browser_executable_folder=...  → (wry 不支持)
# fullscreen_support=True        → fullscreen_handler=自定义处理函数
# no_local_storage=True          → (已移除，使用 incognito=True)

# 已移除的参数（无对等项）：
# context_menus, init_settings_hook

# v0.6.0 新增参数：
# html, headers, navigation_handler, incognito, autoplay,
# javascript_enabled, hotkeys_zoom, drag_drop_handler,
# js_apis, wsgi_executor, fullscreen_handler, parent, native_child
```

## 📦 API 概览

```python
webview = QtWebViewWidget(
    url="https://example.com",           # 初始 URL
    html="<h1>Hello</h1>",               # 或初始 HTML
    headers={"Authorization": "Bearer"},  # 自定义 HTTP 头
    user_agent="CustomAgent/1.0",
    debug=True,                            # DevTools 开启
    transparent=False,
    background_color="#1e1e1e",
    navigation_handler=lambda url: True,   # 返回 False 阻止导航
    new_window_handler=lambda url: "allow",
    lazyload=True,                         # 延迟到 showEvent 加载
    js_apis=DictJsBridge(),               # JS API 桥接
    incognito=False,
    user_data_folder="/path/to/cache",
    wsgi_app=flask_app,
    wsgi_scheme="qtwebview",
    wsgi_executor=8,                       # WSGI 线程池大小
    autoplay=False,
    javascript_enabled=True,
    hotkeys_zoom=True,
    drag_drop_handler=lambda evt, paths, pos: True,
    fullscreen_handler=lambda enter: ...,  # 自定义全屏行为
    native_child=False,                    # 锚点窗口模式
    parent=self,                           # 父级 QWidget
)

webview.load_url(url)                     # 导航
webview.load_url_with_headers(url, hdrs)  # 带 header 导航
webview.load_html(html)                   # 加载 HTML
webview.reload()                          # 重新加载
webview.url()                             # 获取当前 URL
webview.eval_js(script)                   # 执行 JS
webview.evaluate_js(script, callback)     # 带回调执行 JS
webview.cookies()                         # 获取所有 cookie
webview.cookies_for_url(url)              # 获取特定 URL 的 cookie
webview.set_cookie(name, value)           # 设置 cookie
webview.delete_cookie(name, url)          # 删除 cookie
webview.open_devtools()                   # 打开 DevTools
webview.close_devtools()                  # 关闭 DevTools
webview.zoom(1.5)                         # 缩放 150%
webview.print()                           # 打印页面
webview.focus()                           # 聚焦 webview
webview.set_background_color(r, g, b, a)  # 设置背景颜色
webview.clear_all_browsing_data()         # 清除缓存

# 信号
webview.signals.page_loaded.connect(lambda evt, url: ...)
webview.signals.title_changed.connect(lambda title: ...)
webview.signals.navigation_requested.connect(lambda url: ...)
webview.signals.new_window_requested.connect(lambda url: ...)
webview.signals.web_message_received.connect(lambda msg: ...)
webview.signals.initialization_done.connect(lambda: ...)
```

## 许可证

版权所有 (c) 2025-2026 Xiaosu。

根据 [Mozilla Public License Version 2.0](https://github.com/xiaosuawa/QtWebView/blob/master/LICENSE) 的条款分发。

