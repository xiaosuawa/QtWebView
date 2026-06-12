# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from .widget import QtWebViewWidget, QtWebView2Widget
from ._bridge import (
    DictJsBridge,
    QtWebViewJsBridge,
    QtWebView2JsBridge,
    QtWebViewSignals,
    QtWebView2ApiBridge
)
