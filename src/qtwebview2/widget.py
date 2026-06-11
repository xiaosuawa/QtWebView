# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""
QtWebView — Qt webview widget powered by wryview (wry).

Embeds a wry WebView as a native child window inside any Qt widget.

**Supported platforms**: Windows, macOS.

**Linux** is **not** currently supported.  The underlying wryview library
compiles and runs on Linux (WebKitGTK), but the integration layer between
Qt's xcb backend and wry's Xlib/GDK code has unresolved issues — PRs
welcome from Linux contributors!  In the meantime, Linux desktop users
can run the app under Wine.
"""

from __future__ import annotations

__lazy_modules__ = ["wryview"]

import concurrent.futures
import functools
import json
import logging
import sys
import typing
import webbrowser
from io import BytesIO
from typing import Callable, Any, Optional, Union
from typing_extensions import deprecated
from qtpy.QtCore import Qt, QObject, Signal, QTimer, QStandardPaths
from qtpy.QtWidgets import QWidget
from qtpy.QtGui import QWindow
from wryview import WebView

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# JS Bridge
# ═══════════════════════════════════════════════════════════════════════════════

class QtWebViewSignals(QObject):
    """Signals emitted by QtWebViewWidget."""
    # WebView events
    initialization_done = Signal()
    page_loaded = Signal(str, str)  # (event: "Started"|"Finished", url)
    title_changed = Signal(str)  # (title)
    navigation_requested = Signal(str)  # (url)
    new_window_requested = Signal(str)  # (url)
    # JS IPC
    web_message_received = Signal(str)  # (json_message)


@deprecated("Use QtWebViewSignals instead")
class QtWebView2ApiBridge(QtWebViewSignals):
    ...


JSONSerializable = Union[dict[str, "JSONSerializable"], list["JSONSerializable"], str, int, float, bool, None]


@typing.runtime_checkable
class QtWebViewJsBridge(typing.Protocol):
    def __call__(self, name, *arg) -> Union[JSONSerializable, Callable[[Callable[[JSONSerializable], Any], Any], Any]]:
        ...


@deprecated("Use QtWebViewJsBridge instead")
class QtWebView2JsBridge(QtWebViewJsBridge):
    ...


class DictJsBridge:
    """Dictionary-based JS API bridge — Python functions callable from JS."""

    def __init__(self, js_apis: Optional[dict[str, Callable[..., JSONSerializable]]] = None):
        self.js_apis = js_apis or {}

    def __call__(self, name, *arg) -> Union[JSONSerializable, Callable[[Callable[[JSONSerializable], Any], Any], Any]]:
        if name in self.js_apis:
            fn = self.js_apis[name]
            if hasattr(fn, "async_func"):
                return fn
            return fn(*arg)
        raise ValueError(f"Undefined JS API: {name}")

    def bind_js_api_func(self, func: Callable, async_func: bool = False, name: Optional[str] = None):
        """ Decorator to bind a Python function to the JS API. """
        name = name or func.__name__
        if async_func:
            setattr(func, "async_func", True)
        self.js_apis[name] = func
        return func


_JS_BRIDGE = """
(function() {
    if (window.qtwebview || window.qtwebview2) return;
    var pending = {};

    function genId() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    window.qtwebview = window.qtwebview2 = {
        api: new Proxy({}, {
            get: function(target, prop) {
                return function() {
                    var callId = genId();
                    var args = Array.prototype.slice.call(arguments);
                    return new Promise(function(resolve, reject) {
                        pending[callId] = {resolve: resolve, reject: reject};
                        window.ipc.postMessage(JSON.stringify({
                            type: "qtwebview", name: prop, params: args, id: callId
                        }));
                    });
                };
            }
        })
    };

    // Listen for Python responses via CustomEvent
    window.addEventListener('qtwebview-response', function(e) {
        if (!e.detail) return;
        var data = typeof e.detail === 'string' ? JSON.parse(e.detail) : e.detail;
        for (var id in pending) {
            if (data.id === id || (data.result !== undefined && pending[id])) {
                pending[id].resolve(data.result);
                delete pending[id];
                return;
            }
            if (data.error) {
                pending[id].reject(new Error(data.error));
                delete pending[id];
                return;
            }
        }
    });
})();
"""

_FULLSCREEN_JS = """
(function() {
    if (Element.prototype.hasOwnProperty('_qtwebview_fs')) return;
    Object.defineProperty(Element.prototype, '_qtwebview_fs', {value: true});

    var _origReqFS = Element.prototype.requestFullscreen;
    var _origExitFS = Document.prototype.exitFullscreen;

    Element.prototype.requestFullscreen = function(opts) {
        window.ipc.postMessage(JSON.stringify({
            type: "qtwebview", name: "__fullscreen__", params: [true], id: "fs"
        }));
        return _origReqFS ? _origReqFS.call(this, opts) : Promise.resolve();
    };

    Document.prototype.exitFullscreen = function() {
        window.ipc.postMessage(JSON.stringify({
            type: "qtwebview", name: "__fullscreen__", params: [false], id: "fs"
        }));
        return _origExitFS ? _origExitFS.call(this) : Promise.resolve();
    };
})();
"""


class _AnchorWindow(QWidget):
    """
    Top-level transparent widget — the WebView's parent window.

    No Qt parent → independent HWND that survives hide / show cycles.
    macOS: ``WA_TranslucentBackground`` prevents the resize flash.
    Windows: no ``WA_TranslucentBackground`` to avoid the layered-window hit-test bug with ``createWindowContainer``.
    """

    def __init__(self):
        super().__init__(None)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        if sys.platform != "win32":
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
        )

    # ── Abandoned approach — kept for reference ────────────────────────
    # We originally used ``WA_TranslucentBackground`` on all platforms with
    # a nearly-transparent paintEvent (alpha=1) to eliminate the resize flash.
    #
    # On Windows, after the anchor is embedded via ``createWindowContainer``,
    # paintEvent stops firing entirely — manual repaint also has no effect.
    # Areas expanded beyond the initial size never receive the alpha=1 fill,
    # so the DWM has nothing to hit-test against and clicks pass through to
    # the desktop.  macOS does not have this problem (no per-pixel hit-test).
    #
    # The fix: drop ``WA_TranslucentBackground`` on Windows.
    #
    # def paintEvent(self, event):
    #     p = QPainter(self)
    #     p.fillRect(self.rect(), QColor(0, 0, 0, 1))
    #     p.end()
    # ────────────────────────────────────────────────────────────────────


def _require_webview(error_if_not_ready: bool = False):
    """Decorator: if webview not ready, queue call or raise error.

    Args:
        error_if_not_ready: If True, raise RuntimeError instead of queuing.
            Use for methods that return values (cookies, url, etc.).
    """

    def decorator(method):
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            if self.is_ready:
                return method(self, *args, **kwargs)
            if error_if_not_ready:
                raise RuntimeError(f"{method.__name__}(): WebView not initialized")
            self._pending_calls.append((method.__name__, args, kwargs))
            return None

        return wrapper

    return decorator


def default_new_window_handler(url: str):
    # Open in the default browser
    webbrowser.open(url)
    return 'deny'


_NOT_GIVEN: Any = object()


# ═══════════════════════════════════════════════════════════════════════════════
# The Widget
# ═══════════════════════════════════════════════════════════════════════════════

class QtWebViewWidget(QWidget):
    def __init__(
            self,
            url: Optional[str] = None,
            html: Optional[str] = None,
            headers: Optional[Union[dict[str, str], list[tuple[str, str]]]] = None,
            user_agent: Optional[str] = None,
            debug: bool = False,
            transparent: bool = False,
            background_color: Optional[str] = None,
            navigation_handler: Optional[Callable[[str], bool]] = None,
            new_window_handler: Optional[Callable[[str], str]] = default_new_window_handler,
            lazyload: bool = True,
            js_apis: Union[dict[str, Callable[..., Any]], QtWebViewJsBridge, None] = None,
            user_data_folder: Optional[str] = None,
            incognito: bool = False,
            wsgi_app: Optional[Callable[..., Any]] = None,
            wsgi_scheme: Optional[str] = None,
            wsgi_executor: Union[concurrent.futures.Executor, int] = 8,
            autoplay: bool = False,
            javascript_enabled: bool = True,
            hotkeys_zoom: bool = True,
            drag_drop_handler: Optional[Callable[[str, list, tuple], bool]] = None,
            fullscreen_handler: Optional[Callable[[bool], None]] = _NOT_GIVEN,
            native_child: bool = False,
            parent: Optional[QWidget] = None,
    ):
        """
        Cross-platform webview widget for Qt, powered by wryview (wry).

        :param url: The initial URL to load.
        :param user_agent: Custom User-Agent string.
        :param debug: Enable DevTools and browser accelerator keys.
        :param transparent: Enable transparent background mode.
        :param background_color: Background color as hex string (e.g. "#1e1e1e").
        :param navigation_handler: Callable(url) → bool. Return False to block navigation.
        :param new_window_handler: Callable(url) → "allow" | "deny".
        :param lazyload: Defer WebView creation to showEvent. Window appears instantly,
            WebView loads after. Enabled by default.
        :param js_apis: Dict or DictJsBridge exposing Python functions to JavaScript
            via ``window.qtwebview.api``.
        :param user_data_folder: Path for persistent WebView2 user data (cache, cookies).
            Defaults to Qt's AppLocalDataLocation.
        :param incognito: Use incognito mode. No cache or cookies persisted.
            Overrides *user_data_folder*.
        :param wsgi_app: A WSGI-compatible app (Flask, Bottle, Django, etc.). Requests
            are served via custom protocol (default scheme ``qtwebview://``) or localhost
            TCP if ``wsgi_scheme="localhost"``.
        :param wsgi_executor: If provided a thread pool executor,
            the WSGI App will be executed in the provided executor.
            If provided a number, the WSGI App will be executed in a thread pool executor
            with the specified number of threads. defaults to 8
        :param wsgi_scheme: Custom protocol scheme for WSGI. Default ``"qtwebview"``.
            Use ``"localhost"`` to switch to a TCP server on 127.0.0.1 with auto port.
        :param autoplay: Allow autoplay of media. Default False.
        :param javascript_enabled: Enable JavaScript. Default True.
        :param hotkeys_zoom: Enable Ctrl+/- zoom. Default True.
        :param drag_drop_handler: Callable(evt_type, paths, position) → bool.
        :param native_child: If True, embed the WebView directly as a native child
            window instead of using an independent anchor window. Simpler,
            but the WebView dies with the parent HWND — avoid for system-tray apps.
            Default False.
        :param fullscreen_handler: Callable(enter: bool) → None. Called when the page
            requests fullscreen (enter=True) or exit fullscreen (enter=False) via the
            JavaScript Fullscreen API.  The default implementation (anchor mode only)
            reparents the webview container into a dedicated fullscreen ``QWidget``.
            In native-child mode the default is a no-op.  Pass ``None`` to disable
            fullscreen interception entirely.
        :param parent: Parent Qt widget.
        """
        super().__init__(parent)

        # ── Config ──
        self._url = url
        self._user_agent = user_agent
        self._debug = debug
        self._transparent = transparent
        self._bg_color = background_color
        self._wsgi_app = wsgi_app
        self._wsgi_scheme = wsgi_scheme

        if isinstance(wsgi_executor, int):
            self._wsgi_executor = concurrent.futures.ThreadPoolExecutor(max_workers=wsgi_executor)
        elif isinstance(wsgi_executor, concurrent.futures.Executor):
            self._wsgi_executor = wsgi_executor
        else:
            raise TypeError("The wsgi_executor parameter must be a thread pool executor or an integer")

        self._wsgi_port = None
        self._html = html
        self._headers = headers
        self._lazyload = lazyload
        self._user_data_folder = user_data_folder
        self._incognito = incognito
        self._autoplay = autoplay
        self._javascript_enabled = javascript_enabled
        self._hotkeys_zoom = hotkeys_zoom
        self._drag_drop_handler = drag_drop_handler
        self._native_child = native_child
        self._fullscreen_handler = (
            self._default_fullscreen_handler
            if fullscreen_handler is _NOT_GIVEN
            else fullscreen_handler
        )
        self.navigation_handler = navigation_handler
        self.newWindow_handler = new_window_handler

        # JS bridge
        if isinstance(js_apis, dict) or js_apis is None:
            self.js_api: QtWebViewJsBridge = DictJsBridge(js_apis)
        elif isinstance(js_apis, QtWebViewJsBridge):
            self.js_api: QtWebViewJsBridge = js_apis
        else:
            raise TypeError("js_apis must be a dict or DictJsBridge")

        self.signals = QtWebViewSignals(self)
        self.bridge = self.signals

        # ── Create webview (deferred to thread for fast startup) ──
        self._webview: Optional[WebView] = None
        self._anchor: Optional[_AnchorWindow] = None
        self._pending_calls: list[tuple[str, tuple, dict]] = []

        if not self._lazyload:
            self._start_webview()

    # ── WebView creation ────────────────────────────────────────────────────

    def _start_webview(self):
        if sys.platform == "linux":
            raise RuntimeError(
                "QtWebView is not yet supported on Linux — PRs welcome! "
                "The underlying wryview library compiles on Linux, but the "
                "Qt xcb ↔ wry Xlib bridge has unresolved issues. "
                "Linux users can run the app under Wine instead."
            )
        if self._native_child:
            self._start_webview_native()
        else:
            self._start_webview_anchor()

    def _start_webview_anchor(self):
        """Create independent transparent QWidget, embed via fromWinId + container."""
        self._anchor = _AnchorWindow()
        hwnd = int(self._anchor.winId())
        view = QWindow.fromWinId(hwnd)
        self._container = QWidget.createWindowContainer(view, self)
        layout = self.layout()
        if layout is None:
            from qtpy.QtWidgets import QVBoxLayout as _Layout
            layout = _Layout(self)
            layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._container)

        if self.isVisible():
            self._anchor.show()

        self._webview = self._make_webview(hwnd)
        self._flush_pending()

    def _start_webview_native(self):
        """Embed WebView directly as a native child of this widget."""
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        hwnd = int(self.winId())
        self._webview = self._make_webview(hwnd)
        self._flush_pending()

    def _resize_webview(self):
        """Resize the webview to fill its container (anchor or widget)."""
        if not self.is_ready:
            return
        if self._native_child:
            w = self.width()
            h = self.height()
        else:
            w = self._container.width()
            h = self._container.height()
        if w > 0 and h > 0:
            self._webview.set_bounds(0, 0, w, h)

    # ── Fullscreen ────────────────────────────────────────────────────────

    def _default_fullscreen_handler(self, enter: bool):
        """Default fullscreen: reparent container into a dedicated fullscreen window."""
        if self._native_child or self._anchor is None or self._container is None:
            return

        if enter:
            layout = self.layout()
            if layout and self._container:
                layout.removeWidget(self._container)

            from qtpy.QtWidgets import QVBoxLayout as _FSLayout

            self._fs_window = QWidget(None, Qt.WindowType.Window)
            self._fs_window.setAutoFillBackground(True)
            fs_layout = _FSLayout(self._fs_window)
            fs_layout.setContentsMargins(0, 0, 0, 0)
            fs_layout.addWidget(self._container)
            self._fs_window.showFullScreen()
            self._resize_webview()
        else:
            self._fs_window.hide()

            layout = self.layout()
            if layout and self._container:
                layout.addWidget(self._container)
                self._container.show()

            self._fs_window.close()
            self._fs_window = None
            self._resize_webview()

    def _make_webview(self, hwnd: int) -> WebView:
        """Build the kwargs dict and create a WebView."""
        init_script = _JS_BRIDGE
        if self._fullscreen_handler is not None:
            init_script += _FULLSCREEN_JS

        kwargs: dict = {
            "initialization_script": init_script,
            "devtools": self._debug,
            "transparent": self._transparent,
            "incognito": self._incognito,
            "autoplay": self._autoplay,
            "javascript_enabled": self._javascript_enabled,
            "hotkeys_zoom": self._hotkeys_zoom,
        }
        if self._drag_drop_handler:
            kwargs["drag_drop_handler"] = self._drag_drop_handler
        # Auto-generate cache directory unless incognito
        if self._incognito:
            if self._user_data_folder:
                logger.warning("user_data_folder is ignored when incognito=True")
        else:
            data_dir = self._user_data_folder
            if not data_dir:
                data_dir = QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
                if data_dir:
                    data_dir = f"{data_dir}/QtWebView/"
            logger.debug(f"WebView DataFolder: {data_dir}")
            kwargs["data_directory"] = data_dir
        if self._user_agent:
            kwargs["user_agent"] = self._user_agent
        if self._bg_color:
            c = self._bg_color.lstrip("#")
            if len(c) == 6:
                kwargs["background_color"] = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)

        if self._wsgi_app:
            if self._wsgi_scheme == "localhost":
                _wsgi_executor = self._wsgi_executor
                from wsgiref.simple_server import make_server, WSGIServer
                from socketserver import ThreadingMixIn
                import threading

                class ThreadedServer(ThreadingMixIn, WSGIServer):
                    def process_request(self, request, client_address):
                        _wsgi_executor.submit(self.process_request_thread, request, client_address)

                server = make_server("127.0.0.1", 0, self._wsgi_app, server_class=ThreadedServer)
                self._wsgi_port = server.server_port
                threading.Thread(target=server.serve_forever, daemon=True).start()
                logger.info("WSGI on http://127.0.0.1:%d", self._wsgi_port)
            else:
                scheme = self._wsgi_scheme or "qtwebview"
                kwargs["custom_protocols"] = {scheme: self._wsgi_handler}
                self._wsgi_scheme = scheme
                logger.info("WSGI custom protocol: %s://", scheme)

        kwargs["ipc_handler"] = self._on_ipc
        kwargs["on_page_load"] = lambda evt, url: self.bridge.page_loaded.emit(evt, url)
        kwargs["on_title_changed"] = lambda title: self.bridge.title_changed.emit(title)
        kwargs["on_navigation"] = lambda url: (
            self.bridge.navigation_requested.emit(url),
            self.navigation_handler(url) if self.navigation_handler else True
        )[1]
        kwargs["on_new_window"] = lambda url: (
            self.bridge.new_window_requested.emit(url),
            self.newWindow_handler(url) if self.newWindow_handler else "allow"
        )[1]

        if self._html:
            kwargs["html"] = self._html
        if self._user_data_folder:
            kwargs["data_directory"] = self._user_data_folder

        if self._wsgi_port:
            kwargs["url"] = f"http://127.0.0.1:{self._wsgi_port}/"
        elif self._wsgi_scheme:
            kwargs["url"] = f"{self._wsgi_scheme}://localhost/"
        elif self._url:
            kwargs["url"] = self._url

        if self._headers:
            kwargs["headers"] = self._headers

        # Initial size — fill the container (or widget for native mode)
        if self.width() > 0 and self.height() > 0:
            kwargs["width"] = self.width()
            kwargs["height"] = self.height()

        QTimer.singleShot(0, self._resize_webview)

        return WebView(hwnd, **kwargs)

    def _flush_pending(self):
        for name, args, kwargs in self._pending_calls:
            getattr(self, name)(*args, **kwargs)
        self._pending_calls.clear()

        self.signals.initialization_done.emit()

    # ── IPC ──────────────────────────────────────────────────────────────────

    def _on_ipc(self, msg: str):
        self.signals.web_message_received.emit(msg)
        try:
            data = json.loads(msg)
            # Only process internal bridge calls
            if data.get("type") != "qtwebview":
                return

            func_name = data.get("name", "")
            params = data.get("params", [])
            call_id = data.get("id", "")

            # Fullscreen API interception
            if func_name == "__fullscreen__":
                if self._fullscreen_handler:
                    enter = bool(params[0]) if params else True
                    self._fullscreen_handler(enter)
                return

            if func_name == "call":
                func_name = params[0] if params else ""
                params = params[1:] if len(params) > 1 else []

            if not func_name or not call_id:
                return

            try:
                res = self.js_api(func_name, *params)
                if callable(res):
                    res(lambda result: self._return_to_js(result, call_id))
                else:
                    self._return_to_js(res, call_id)
            except Exception as e:
                logger.error("JS API '%s' error: %s", func_name, e, exc_info=True)
                self._return_js_error(repr(e), call_id)
        except (json.JSONDecodeError, KeyError, TypeError):
            self.signals.web_message_received.emit(msg)
            logger.debug("Raw IPC: %.200s", msg)

    def _return_to_js(self, result: Any, call_id: str):
        payload = json.dumps({"id": call_id, "result": result})
        self._webview.eval_js(
            f"window.dispatchEvent(new CustomEvent('qtwebview-response', {{detail: {payload}}}));"
        )

    def _return_js_error(self, error: str, call_id: str):
        payload = json.dumps({"id": call_id, "error": error})
        self._webview.eval_js(
            f"window.dispatchEvent(new CustomEvent('qtwebview-response', {{detail: {payload}}}));"
        )

    # ── WSGI ────────────────────────────────────────────────────────────────

    def _wsgi_handler(
            self, method: str, uri: str, headers: list, body: bytes, respond: Callable,
    ):
        """wryview custom protocol → WSGI adapter (async: calls respond when done)."""
        from urllib.parse import urlparse
        parsed = urlparse(uri)

        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": parsed.path or "/",
            "QUERY_STRING": parsed.query or "",
            "SERVER_NAME": self._wsgi_scheme or "",
            "SERVER_PORT": "80",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "HTTP_HOST": self._wsgi_scheme or "",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": BytesIO(body),
            "wsgi.errors": BytesIO(),
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }

        for k, v in headers:
            key = "HTTP_" + k.upper().replace("-", "_")
            if key not in ("HTTP_CONTENT_TYPE", "HTTP_CONTENT_LENGTH"):
                environ[key] = v
        for k_lower, wsgi_key in (("content-type", "CONTENT_TYPE"), ("content-length", "CONTENT_LENGTH")):
            for k, v in headers:
                if k.lower() == k_lower:
                    environ[wsgi_key] = v
                    break

        def _run():
            status_info = {}

            def start_response(status, response_headers, exc_info=None):
                status_info["status"] = status
                status_info["headers"] = response_headers

            try:
                result = self._wsgi_app(environ, start_response)
            except Exception as e:
                logger.error("WSGI error: %s", e, exc_info=True)
                respond(500, [], b"Internal Server Error")
                return

            if "status" not in status_info:
                respond(500, [], b"WSGI app did not call start_response")
                return

            status_code = int(status_info["status"].split(" ", 1)[0])
            body_chunks = []
            for chunk in result:
                body_chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
            respond(status_code, status_info.get("headers", []), b"".join(body_chunks))

        self._wsgi_executor.submit(_run)

    # ── Public API ──────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """True once the underlying WebView has been created."""
        return self._webview is not None

    def load_url(self, url: str, headers: Optional[Union[dict, list]] = None):
        """Navigate to a URL."""
        if headers is None:
            headers = []
        if self.is_ready:
            if headers:
                self._webview.load_url_with_headers(url, headers)
            else:
                self._webview.load_url(url)
        else:
            self._url = url
            self._pending_calls.append(('load_url', (url, headers), {}))

    @_require_webview()
    def load_url_with_headers(self, url: str, headers: Union[dict, list]):
        """Navigate to URL with custom HTTP headers."""
        self._webview.load_url_with_headers(url, headers)

    @_require_webview()
    def load_html(self, html: str):
        """Load HTML content directly."""
        self._webview.load_html(html)

    def url(self) -> str | None:
        if self.is_ready:
            return self._webview.url()
        else:
            return self._url

    @_require_webview()
    def reload(self):
        """Reload the current page."""
        self._webview.reload()

    @_require_webview()
    def evaluate_js(self, script: str, callback: Optional[Callable[[str], None]] = None):
        """Execute JavaScript. If *callback* is given, receives the result string."""
        if callback:
            self._webview.eval_js_with_callback(script, callback)
        else:
            self._webview.eval_js(script)

    def eval_js(self, script: str, callback: Optional[Callable[[str], None]] = None):
        """
        Execute JavaScript. If *callback* is given, receives the result string.
        (convenience alias for evaluate_js)
        """
        self.evaluate_js(script, callback)

    @_require_webview()
    def open_devtools(self):
        """Open the browser DevTools window."""
        self._webview.open_devtools()

    @_require_webview()
    def close_devtools(self):
        """Close the browser DevTools window."""
        self._webview.close_devtools()

    @_require_webview()
    def zoom(self, scale: float):
        """Set zoom level (1.0 = 100%)."""
        self._webview.zoom(scale)

    def showEvent(self, event):
        super().showEvent(event)
        if self._lazyload and not self.is_ready:
            QTimer.singleShot(0, self._start_webview)
        elif self._anchor:
            self._anchor.show()
        elif self._webview:
            self._webview.set_visible(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._anchor:
            self._anchor.hide()
        elif self._webview:
            self._webview.set_visible(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_webview()

    def closeEvent(self, event):
        self._webview = None
        if self._anchor:
            self._anchor.deleteLater()
            self._anchor = None
        super().closeEvent(event)

    # ── Cookie ────────────────────────────────────────────────────────

    @_require_webview()
    def set_cookie(self, name: str, value: str, domain: Optional[str] = None, path: Optional[str] = None):
        """Set a cookie."""
        self._webview.set_cookie(name, value, domain, path)

    @_require_webview(error_if_not_ready=True)
    def cookies(self) -> list:
        """Get all cookies."""
        return self._webview.cookies()

    @_require_webview(error_if_not_ready=True)
    def cookies_for_url(self, url: str) -> list:
        """Get cookies for a specific URL."""
        return self._webview.cookies_for_url(url)

    @_require_webview()
    def delete_cookie(self, name: str, url: str):
        """Delete a cookie."""
        self._webview.delete_cookie(name, url)

    # ── Misc ───────────────────────────────────────────────────────────

    @_require_webview()
    def set_background_color(self, r: int, g: int, b: int, a: int = 255):
        """Set background color after creation."""
        self._webview.set_background_color(r, g, b, a)

    @_require_webview()
    def focus(self):
        """Focus the webview."""
        self._webview.focus()

    @_require_webview()
    def print(self):
        """Print the current page."""
        self._webview.print()

    @_require_webview()
    def clear_all_browsing_data(self):
        """Clear all browsing data (cache, cookies, storage)."""
        self._webview.clear_all_browsing_data()


@deprecated("Use QtWebViewWidget instead")
class QtWebView2Widget(QtWebViewWidget):
    ...
