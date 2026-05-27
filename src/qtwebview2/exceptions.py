# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

class QtWebviewException(Exception):
    """Base class for exceptions in this module."""
    pass


class WebviewInitException(QtWebviewException):
    """Exception raised when the webview cannot be initialized."""
    pass
