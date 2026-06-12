# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""JS Bridge — signals, protocol, and dictionary-based API bridge."""
from __future__ import annotations

import typing
from typing import Callable, Any, Optional, Union
from typing_extensions import deprecated
from qtpy.QtCore import QObject, Signal


# ═══════════════════════════════════════════════════════════════════════════════
# Signals
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


# ═══════════════════════════════════════════════════════════════════════════════
# JS API bridge protocol & default implementation
# ═══════════════════════════════════════════════════════════════════════════════

JSONSerializable = Union[dict[str, "JSONSerializable"], list["JSONSerializable"],
str, int, float, bool, None]


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


# ═══════════════════════════════════════════════════════════════════════════════
# JavaScript payloads injected into every WebView
# ═══════════════════════════════════════════════════════════════════════════════

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
