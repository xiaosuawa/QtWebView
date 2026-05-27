# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import json
import os
import threading
import typing
import uuid
import webbrowser
import concurrent.futures
from typing import Callable, Any, Optional, Union

import win32con
import win32gui

from qtpy.QtCore import Qt, Slot, QObject, Signal, QCoreApplication, QTimer, QStandardPaths
from qtpy.QtWidgets import QWidget

from .logger import logger
from . import exceptions
from . import _dotnet_bridge as dotnet


class QtWebView2ApiBridge(QObject):
    """
    Helper QObject to safely pass signals from the .NET thread to the Qt main GUI thread.
    """
    initialization_done = Signal(bool, str)  # Parameters: success, error_message
    web_message_received = Signal(str)  # Parameters: message
    js_evaluation_result = Signal(str, str)  # Parameters: call_id, result_json
    async_result_ready = Signal(dict, str)  # Parameters: result, call_id
    execute_js_from_thread = Signal(str)  # Parameters: js_code
    domContentLoaded = Signal()
    fullscreen_changed = Signal(bool)  # Parameters: is_fullscreen


JSONSerializable = Union[dict[str, "JSONSerializable"], list["JSONSerializable"], str, int, float, bool, None]


@typing.runtime_checkable
class QtWebView2JsBridge(typing.Protocol):
    def __call__(self, name, *arg) -> Union[JSONSerializable, Callable[[Callable[[JSONSerializable], Any], Any], Any]]:
        ...


class DictJsBridge:
    def __init__(self, js_apis: Optional[dict[str, Callable[..., JSONSerializable]]] = None):
        self.js_apis = js_apis if js_apis is not None else {}

    def __call__(self, name, *arg) -> Union[JSONSerializable, Callable[[Callable[[JSONSerializable], Any], Any], Any]]:
        if name in self.js_apis:
            # For asynchronous functions, return the function itself
            if hasattr(self.js_apis[name], 'async_func'):
                return self.js_apis[name]
            # For synchronous functions, call directly and return the result
            return self.js_apis[name](*arg)
        else:
            raise ValueError(f"Undefined JS API: {name}")

    def bind_js_api_func(self, func: Callable, async_func: bool = False, name: str = None):
        """ Decorator to bind a Python function to the JS API. """
        name = name or func.__name__
        if async_func:
            setattr(func, 'async_func', True)
        self.js_apis[name] = func
        return func


class QtWebView2Widget(QWidget):
    """
    QtPy WebView2 Widget
    """

    _wsgi_response_ready = Signal(object, object, str, list, object)
    _init_webview2_signal = Signal()

    def __init__(
            self,
            url: Optional[str] = None,
            user_agent: Optional[str] = None,
            debug: bool = False,
            context_menus: bool = False,
            transparent: bool = False,
            background_color: Optional[str] = None,
            handle_new_window: bool = True,
            lazyload: bool = True,
            js_apis: Union[dict[str, Callable[..., Any]], QtWebView2JsBridge, None] = None,
            user_data_folder: Optional[str] = None,
            no_local_storage: bool = False,
            wsgi_app: Optional[Callable[..., Any]] = None,
            wsgi_host_name: Optional[str] = None,
            wsgi_executor: Union[concurrent.futures.Executor, int] = 8,
            init_settings_hook: Optional[Callable[[Any], None]] = None,
            fullscreen_support: bool = True,
            browser_executable_folder: Optional[str] = None,
            parent: Optional[QWidget] = None,
    ):
        """
        QtPy WebView2 Widget
        :param url: The target URL
        :param user_agent: User-Agent string for the request header, defaults if left empty
        :param debug: Whether to enable debug mode. Disabling it will turn off hotkeys and dev tools. If disabled, it's
          recommended to also disable context_menus.
        :param context_menus: Whether to enable the right-click context menu
        :param transparent: Whether to use transparent mode (this has a bug when switching pages; remember to set the
          body's background color style to transparent for it to work)
        :param background_color: Background color, conflicts with transparent
        :param handle_new_window: Whether to handle new windows. If enabled, the target URL will be opened in the user's
          default browser
        :param lazyload: Whether to lazy load. Enabled by default. If enabled, webview2 will only be loaded when the
          widget becomes visible for the first time.
        :param js_apis: JS API, can be a dictionary or a class conforming to the QtWebView2JsBridge protocol. A
          dictionary will be automatically converted to DictJsBridge. If not provided, an empty DictJsBridge is created.
        :param user_data_folder: User data directory. If not provided, it will be generated automatically.
        :param no_local_storage: Whether to disable local storage. Note: Disabling it may affect performance.
        :param wsgi_app: If provided, the network request from WebView2 will be intercepted and handed over to the
          provided WSGI App for processing
        :param wsgi_host_name: If provided, only requests that meet the wsgi_host_name will be handed over to the
          WSGI App for processing
        :param wsgi_executor: If provided a thread pool executor,
          the WSGI App will be executed in the provided executor.
          If provided a number, the WSGI App will be executed in a thread pool executor
          with the specified number of threads. defaults to 8
        :param init_settings_hook: A callback function that takes 'CoreWebView2' as an argument.
          Executed before loading the URL but after initialization.
        :param fullscreen_support: If True, automatically handles window fullscreen toggling when
          the web element requests fullscreen.
        :param browser_executable_folder: Path to a fixed-version WebView2 runtime. When provided,
          the bundled runtime is used instead of the system's Evergreen runtime. The path should
          point to a folder containing msedgewebview2.exe.
        :param parent: Parent widget
        """
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)

        self._init_webview2_signal.connect(self._init_webview)

        self._lazyload = lazyload
        if self._lazyload and not dotnet.dotnet_load_flag:
            threading.Thread(target=dotnet.load_dotnet_env, daemon=True).start()

        # --- Configuration Properties ---
        self.url = url
        if isinstance(js_apis, dict) or js_apis is None:
            self.js_api: QtWebView2JsBridge = DictJsBridge(js_apis)
        elif isinstance(js_apis, QtWebView2JsBridge):
            self.js_api: QtWebView2JsBridge = js_apis
        else:
            raise TypeError("The js_apis parameter must be a dictionary or a QtWebView2JsBridge compatible object")

        self.wsgi_app = wsgi_app
        self.wsgi_host_name = wsgi_host_name or "qtwebview2.local"
        self._wsgi_server = None
        if isinstance(wsgi_executor, int):
            self._wsgi_executor = concurrent.futures.ThreadPoolExecutor(max_workers=wsgi_executor)
        elif isinstance(wsgi_executor, concurrent.futures.Executor):
            self._wsgi_executor = wsgi_executor
        else:
            raise TypeError("The wsgi_executor parameter must be a thread pool executor or an integer")

        self._wsgi_response_ready.connect(self._finalize_wsgi_response)

        if self.wsgi_app and not self.wsgi_host_name:
            raise ValueError("wsgi_host_name must be provided when wsgi_app is set.")

        self.is_ready = False
        self._user_agent = user_agent
        self._debug_enabled = debug
        self._context_menus_enabled = context_menus
        self._is_transparent = transparent
        self.background_color = background_color
        self._handle_new_window = handle_new_window
        self._user_data_folder = user_data_folder
        self._no_local_storage = no_local_storage
        self._init_settings_hook = init_settings_hook
        self._fullscreen_support = fullscreen_support
        self._browser_executable_folder = browser_executable_folder

        # --- Internal State ---
        if typing.TYPE_CHECKING:
            self._webview: Optional[dotnet.WinForms.WebView2] = None
        else:
            self._webview = None
        self._webview_hwnd: Optional[int] = None
        self._js_callbacks: dict[str, Callable[..., Any]] = {}
        self._saved_window_state = None

        # Thread-safe signal bridge
        self.bridge = QtWebView2ApiBridge(self)
        self.bridge.initialization_done.connect(self._on_initialization_completed)
        self.bridge.web_message_received.connect(self._on_web_message_received)
        self.bridge.js_evaluation_result.connect(self._on_js_evaluation_result)
        self.bridge.async_result_ready.connect(self._return_result_to_js)
        self.bridge.execute_js_from_thread.connect(self._execute_script_in_main_thread)

        if self._fullscreen_support:
            self.bridge.fullscreen_changed.connect(self._default_on_fullscreen_change)

        self._resize_throttle_timer = QTimer(self)
        self._resize_throttle_timer.setSingleShot(True)
        self._resize_throttle_timer.setInterval(int(1000 / 60))
        self._resize_throttle_timer.timeout.connect(self._resize_webview)

        if not self._lazyload:
            if not dotnet.dotnet_load_flag:
                threading.Thread(
                    target=lambda: dotnet.load_dotnet_env(self._init_webview2_signal.emit),
                    daemon=True
                ).start()
            else:
                QTimer.singleShot(0, self._init_webview)

        self._pending_calls = []  # Store calls made before initialization
        self._has_shown = False

    def showEvent(self, event):
        super().showEvent(event)
        if self._lazyload and not self._has_shown:
            self._has_shown = True
            QTimer.singleShot(0, self._init_webview)

        if self.is_ready:
            self._webview.Visible = True

    def hideEvent(self, event):
        if self.is_ready:
            self._webview.Visible = False
        super().hideEvent(event)

    def _init_webview(self):
        """
        Asynchronously initializes the WebView2 control.
        """

        if self._webview:
            logger.warning("WebView2 already initialized", stack_info=True)
            return

        dotnet.load_dotnet_env()
        try:
            self._webview = dotnet.WinForms.WebView2()
            self._webview.CoreWebView2InitializationCompleted += self._on_webview_ready
            self._webview.WebMessageReceived += self._on_script_notify

            if self._is_transparent:
                self._webview.DefaultBackgroundColor = dotnet.System_.Drawing.Color.Transparent
            elif self.background_color:
                self._webview.DefaultBackgroundColor = dotnet.System_.Drawing.ColorTranslator.FromHtml(
                    self.background_color
                )

            if self._no_local_storage:
                user_data = None
                logger.debug("WebView2 local storage is disabled")
            else:
                user_data = self._user_data_folder
                if not self._user_data_folder:
                    app_name = QCoreApplication.applicationName() or "DefaultQtApp"
                    data_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
                    if not data_path:
                        data_path = os.path.join(dotnet.System_.IO.Path.GetTempPath(), app_name)
                    user_data = os.path.join(data_path, "WebView2_UserData")
                logger.debug(f"WebView2 UserDataFolder: {user_data}")

            if self._browser_executable_folder is not None:
                # Fixed-version: use bundled WebView2 runtime
                env_task = dotnet.Core.CoreWebView2Environment.CreateAsync(
                    self._browser_executable_folder,
                    user_data,
                )
                env_task.Wait()
                if env_task.IsFaulted:
                    raise env_task.Exception.InnerException or env_task.Exception
                self._webview.EnsureCoreWebView2Async(env_task.Result)
            else:
                # Evergreen: use system WebView2 runtime via implicit initialization
                props = dotnet.WinForms.CoreWebView2CreationProperties()
                if user_data:
                    props.UserDataFolder = user_data
                self._webview.CreationProperties = props
                self._webview.EnsureCoreWebView2Async(None)

        except Exception as e:
            logger.error(f"Could not start WebView2 initialization: {repr(e)}", exc_info=True)
            self.bridge.initialization_done.emit(False, str(e))
            raise exceptions.WebviewInitException(e)

    def _on_webview_ready(self, sender: dotnet.WinForms.WebView2,
                          args: dotnet.Core.CoreWebView2InitializationCompletedEventArgs):
        """ .NET event handler, executed on a non-Qt thread. Emits a signal to return control to the Qt main thread. """
        if not args.IsSuccess:
            error_msg = str(args.InitializationException)
            logger.error(f"WebView2 initialization failed: {error_msg}")
            self.bridge.initialization_done.emit(False, error_msg)
            return

        sender.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(self._get_jsbridge_script())
        self.bridge.initialization_done.emit(True, "")

    @Slot(bool, str)
    def _on_initialization_completed(self, success: bool, error_message: str):
        """ Qt slot, safely performs all UI-related initialization work in the main UI thread. """
        if not success:
            logger.error(f"WebView initialization error: {error_message}")
            self.deleteLater()
            return

        # CoreWebView2 is now ready and can be configured
        core_webview = self._webview.CoreWebView2
        settings = self._webview.CoreWebView2.Settings
        settings.IsScriptEnabled = True
        settings.IsWebMessageEnabled = True
        settings.AreDefaultScriptDialogsEnabled = True

        # --- Apply startup parameters ---
        settings.AreDevToolsEnabled = self._debug_enabled
        settings.AreBrowserAcceleratorKeysEnabled = self._debug_enabled
        settings.AreDefaultContextMenusEnabled = self._context_menus_enabled
        if self._user_agent:
            settings.UserAgent = self._user_agent

        if self._handle_new_window:
            self._webview.CoreWebView2.NewWindowRequested += self._on_new_window_request

        core_webview.ContainsFullScreenElementChanged += self._on_contains_fullscreen_element_changed

        if self._init_settings_hook:
            try:
                self._init_settings_hook(core_webview)
            except Exception as e:
                logger.error(f"Error in init_settings_hook: {repr(e)}", exc_info=True)

        self.is_ready = True
        self._webview_hwnd = self._webview.Handle.ToInt32()

        # Embed the window and adjust the style
        win32gui.SetParent(self._webview_hwnd, int(self.winId()))
        style = win32gui.GetWindowLong(self._webview_hwnd, win32con.GWL_STYLE)
        win32gui.SetWindowLong(self._webview_hwnd, win32con.GWL_STYLE, style & ~win32con.WS_BORDER | win32con.WS_CHILD)

        self._webview.Visible = self.isVisible()

        self._webview.CoreWebView2.DOMContentLoaded += lambda sender, args: self.bridge.domContentLoaded.emit()

        if self.wsgi_app:
            logger.info(f"WSGI application detected. Intercepting requests for host: {self.wsgi_host_name}")
            from .wsgi_server import WebView2WSGIServer
            self._wsgi_server = WebView2WSGIServer(self.wsgi_app)

            self._webview.CoreWebView2.AddWebResourceRequestedFilter(
                f"http://{self.wsgi_host_name}/*",
                dotnet.Core.CoreWebView2WebResourceContext.All
            )
            self._webview.CoreWebView2.AddWebResourceRequestedFilter(
                f"https://{self.wsgi_host_name}/*",
                dotnet.Core.CoreWebView2WebResourceContext.All
            )

            self._webview.CoreWebView2.WebResourceRequested += self._on_web_resource_requested

        win32gui.ShowWindow(self._webview_hwnd, win32con.SW_SHOW)

        self._resize_webview()

        if self.url:
            self.load_url(self.url)

        for method_name, args, kwargs in self._pending_calls:
            getattr(self, method_name)(*args, **kwargs)
        self._pending_calls.clear()

    def _on_contains_fullscreen_element_changed(self, sender, args):
        is_full = sender.ContainsFullScreenElement
        self.bridge.fullscreen_changed.emit(is_full)

    def _on_web_resource_requested(self, sender, args):
        from .wsgi_server import extract_request_data
        try:
            deferral = args.GetDeferral()
            req_data = extract_request_data(args)
            self._wsgi_executor.submit(self._run_wsgi_in_background, args, deferral, req_data)

        except Exception as e:
            logger.error(f"Error preparing WSGI request: {e}", exc_info=True)
            pass

    def _run_wsgi_in_background(self, args, deferral, req_data):
        try:
            status, headers, iterator = self._wsgi_server.process_wsgi_request(req_data)
            self._wsgi_response_ready.emit(args, deferral, status, headers, iterator)
        except Exception as e:
            logger.error(f"Error in WSGI worker thread: {e}", exc_info=True)
            self._wsgi_response_ready.emit(args, deferral, "500 Internal Server Error", [], None)

    @Slot(bool)
    def _default_on_fullscreen_change(self, is_fullscreen: bool):
        window = self.window()
        if not window:
            return

        if is_fullscreen:
            self._saved_window_state = window.windowState()
            window.showFullScreen()
        else:
            if self._saved_window_state is not None:
                window.setWindowState(self._saved_window_state)
            else:
                window.showNormal()

    @Slot(object, object, str, list, object)
    def _finalize_wsgi_response(self, args, deferral, status, headers, iterator):
        from .wsgi_server import PythonGeneratorStream
        try:
            if not status or status.startswith('500') or iterator is None:
                reason_phrase = "Internal Server Error"
                status_code = 500
                content_stream = None
            else:
                parts = status.split(' ', 1)
                status_code = int(parts[0])
                reason_phrase = parts[1] if len(parts) > 1 else "OK"

                content_stream = PythonGeneratorStream(iterator)

            env = self._webview.CoreWebView2.Environment
            response = env.CreateWebResourceResponse(
                content_stream,
                status_code,
                reason_phrase,
                ""
            )

            if headers:
                for name, value in headers:
                    try:
                        response.Headers.AppendHeader(name, value)
                    except Exception:
                        pass

            args.Response = response

        except Exception as e:
            logger.error(f"Error finalizing WSGI response: {e}", exc_info=True)
        finally:
            if deferral:
                try:
                    deferral.Complete()
                except Exception as e:
                    logger.warning(f"Failed to complete deferral (page might be closed): {e}")

    def _on_new_window_request(self, sender, args):
        uri_string = args.Uri

        logger.debug(f"New window request: {uri_string}")

        # Open in the default browser
        webbrowser.open(uri_string)
        args.Handled = True

    def _on_script_notify(self, sender,
                          args: dotnet.Core.CoreWebView2WebMessageReceivedEventArgs):
        try:
            self.bridge.web_message_received.emit(args.WebMessageAsJson)
        except Exception as e:
            logger.error(f"Error processing web message: {e}")

    @Slot(str)
    def _on_web_message_received(self, message: str):
        try:
            data = json.loads(message)
            func_name, params, call_id = data['name'], data['params'], data['id']
        except (json.JSONDecodeError, KeyError):
            logger.warning(f"Received invalid message from JS bridge: {message}")
            return

        if func_name == '_qtwebviewCallback':
            self.bridge.js_evaluation_result.emit(call_id, json.dumps(params))
        elif func_name == 'call':
            self._on_web_message_received(json.dumps({"name": params[0], "params": params[1:], "id": call_id}))
        else:
            logger.debug(f"Executing JS API function '{func_name}': {params}")
            try:
                res = self.js_api(func_name, *params)
                if callable(res):  # async function
                    thread_safe_callback = lambda result: self.bridge.async_result_ready.emit(
                        {'result': result}, call_id
                    )
                    res(thread_safe_callback, *params)
                else:  # sync function
                    self._return_result_to_js({'result': res}, call_id)
            except Exception as e:
                logger.error(f"Error executing JS API function '{func_name}': {e}", exc_info=True)
                self._return_result_to_js({'error': str(e)}, call_id)

    def _get_jsbridge_script(self) -> str:
        """ Returns the JS bridge script to be injected into the page. """
        return """
            (function() {
                function getUuid() {
                    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
                        var r = (Math.random() * 16) | 0,
                            v = c == 'x' ? r : (r & 0x3) | 0x8;
                        return v.toString(16);
                    });
                }

                window.qtwebview2 = {
                    api: new Proxy({}, {
                        get(target, prop, receiver) {
                            return (...args) => {
                                const id = getUuid();
                                const promise = new Promise((resolve, reject) => {
                                    const handler = (e) => {
                                        if (e.detail.error) {
                                            reject(new Error(e.detail.error));
                                        } else {
                                            resolve(e.detail.result);
                                        }
                                    };
                                    window.addEventListener('qtwebview2-response-' + id, handler, { once: true });
                                });
                                window.chrome.webview.postMessage({
                                    name: prop,
                                    params: args,
                                    id: id
                                });
                                return promise;
                            }
                        }
                    })
                };
            })();
        """

    @Slot(dict, str)
    def _return_result_to_js(self, result_data: dict, call_id: str):
        """ Returns the result of a Python API call to JS. This is now a thread-safe slot. """
        try:
            result_data_json = json.dumps(result_data)
        except Exception as e:
            logger.error(f"Failed to convert result to JSON: {repr(e)}", exc_info=True)
            result_data_json = json.dumps({'error': repr(e)})

        script = (
            f"window.dispatchEvent("
            f"new CustomEvent('qtwebview2-response-{call_id}', {{ detail: {result_data_json} }})"
            f");"
        )
        logger.debug(f"return_result_to_js: {script}")

        self.bridge.execute_js_from_thread.emit(script)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._resize_throttle_timer.isActive():
            self._resize_throttle_timer.start()

    @Slot()
    def _resize_webview(self):
        if self._webview_hwnd:
            dpr = self.devicePixelRatioF()
            if self.window() and self.window().windowHandle():
                dpr = self.window().windowHandle().devicePixelRatio()

            physical_width = int(self.width() * dpr)
            physical_height = int(self.height() * dpr)
            win32gui.MoveWindow(self._webview_hwnd, 0, 0, physical_width, physical_height, True)

    def closeEvent(self, event):
        if self._webview:
            self._webview.Dispose()
        self._wsgi_executor.shutdown(wait=False)
        super().closeEvent(event)

    # --- Public API Methods ---
    def reload(self):
        """Reloads the current page."""
        if self.is_ready:
            self._webview.Reload()
        else:
            self._pending_calls.append(('reload', (), {}))

    def load_url(self, url: str):
        """Loads a URL."""
        if self.is_ready:
            self._webview.Source = dotnet.System_.Uri(url)
        else:
            self._pending_calls.append(('load_url', (url,), {}))

    def load_html(self, html: str, base_uri: Optional[str] = None):
        """Loads HTML."""
        if self.is_ready:
            self._webview.NavigateToString(html)
        else:
            self._pending_calls.append(('load_html', (html,), {'base_uri': base_uri}))

    def evaluate_js(self, script: str, callback: Optional[Callable[[dict], None]] = None):
        """
        Executes JavaScript. If a callback is provided, it will be called with a dictionary
        containing the success/failure status and the result/error.
        This method is thread-safe.
        """
        if not self.is_ready:
            self._pending_calls.append(('evaluate_js', (script,), {'callback': callback}))
            return

        call_id = uuid.uuid4().hex
        if callback:
            self._js_callbacks[call_id] = callback

        wrapped_script = f"""
            (async function() {{
                try {{
                    const result = await (async () => {{ {script} }})();
                    window.chrome.webview.postMessage({{
                        name: '_qtwebviewCallback',
                        params: {{'success': true, 'result': result === undefined ? null : result}},
                        id: '{call_id}'
                    }});
                }} catch (e) {{
                    window.chrome.webview.postMessage({{
                        name: '_qtwebviewCallback',
                        params: {{'success': false, 'error': e.toString()}},
                        id: '{call_id}'
                    }});
                }}
            }})();
        """
        self.bridge.execute_js_from_thread.emit(wrapped_script)

    @Slot(str)
    def _execute_script_in_main_thread(self, script: str):
        if not self.is_ready:
            self._pending_calls.append(('_execute_script_in_main_thread', (script,), {}))
            return
        self._webview.ExecuteScriptAsync(script)

    @Slot(str, str)
    def _on_js_evaluation_result(self, call_id: str, result_json: str):
        """ Handles the callback for evaluate_js in the Qt main thread. """
        callback = self._js_callbacks.pop(call_id, None)
        if callback:
            try:
                result_dict = json.loads(result_json)
                callback(result_dict)
            except Exception as e:
                logger.error(f"Error processing JS callback: {e}", exc_info=True)

    def hasFocus(self):
        # Check if _webview exists and has not been disposed
        if self._webview and not self._webview.IsDisposed:
            return self._webview.ContainsFocus
        return super().hasFocus()
