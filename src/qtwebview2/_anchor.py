# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""

``_AnchorWindow`` — top-level transparent host for the WebView child HWND.

On Windows the window is made layered (per-pixel alpha via
``WS_EX_LAYERED``) so that resize events can fill newly-exposed pixels
with alpha=1 — eliminating the black-edge flicker that the DWM would
otherwise produce when the layered surface is extended during resize.

See the class docstring for a detailed rationale.
"""
from __future__ import annotations

import sys
from qtpy.QtCore import Qt, QTimer
from qtpy.QtWidgets import QWidget


class _AnchorWindow(QWidget):
    """
    Top-level window that hosts the WebView child HWND.

    **Why this class exists**

    Windows WebView2 resizing produces a black-edge flicker.  The flicker
    comes from the DWM layered surface being extended before any new
    content is submitted — the DWM fills the new area with transparent
    black, which the user sees as a brief black flash at the window edge.

    The known fix is per-pixel alpha: fill every pixel of the layered
    surface with alpha=1 (visually transparent, but alpha>0 tells the
    DWM the pixel belongs to this window → hit-test passes).  Qt provides
    this via ``WA_TranslucentBackground`` + ``paintEvent``, but
    ``createWindowContainer`` suppresses *paintEvent* on the embedded
    window, so newly-exposed areas never receive the alpha=1 fill during
    resize.

    **How this class works around it**

    1. ``WA_TranslucentBackground`` — Qt creates the window with
       ``WS_EX_LAYERED`` and handles the *initial* layered surface setup.

    2. ``nativeEvent`` catches ``WM_SIZE`` — during a resize the window's
       layered surface is extended by the DWM (new area = alpha=0).  We
       immediately schedule (throttled) or directly call ``_fill_layered``
       which submits a fresh 32-bit BGRA bitmap via the Win32
       ``UpdateLayeredWindow`` API — bypassing Qt's paint machinery entirely.

    3. Throttling (~30 fps via ``_fill_timer``) — calling
       ``UpdateLayeredWindow`` on every ``WM_SIZE`` (which fires 60–120
       times/sec during a mouse drag) causes the DWM to re-composite the
       entire window each time, making the WebView content flicker.
       Throttling to ~30 fps reduces the flicker to an acceptable level
       while still updating quickly enough that the resize feels responsive.
       ``WM_EXITSIZEMOVE`` (0x0232) triggers an immediate final update.

    4. Cached DIB section — creating a new 32-bit bitmap on every call
       is wasteful.  We cache the GDI objects and only recreate them when
       the window grows beyond the cached size.

    5. The bitmap is filled with BGRA ``(0, 0, 0, 1)`` — premultiplied
       alpha where every pixel has alpha=1.  The DWM does per-pixel
       hit-testing: alpha>0 means the pixel belongs to this window, so
       clicks are registered even though the pixel is visually transparent
       (1/255 opacity).

    **Why not use ``WA_TranslucentBackground`` + ``repaint()``?**

    ``createWindowContainer`` stops ``paintEvent`` (and ``WM_PAINT``)
    from reaching the embedded window for newly-exposed areas.  Calling
    ``repaint()``, ``update()``, or even direct QPainter painting has no
    effect — Qt's internal foreign-window integration simply does not
    route those paint operations to the layered surface.  The only
    reliable path is to call ``UpdateLayeredWindow`` ourselves.
    """

    def __init__(self):
        super().__init__(None)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
        )
        # Single-shot timer for WM_SIZE throttling
        self._fill_timer = QTimer(self)
        self._fill_timer.setSingleShot(True)
        self._fill_timer.timeout.connect(self._fill_layered)

    # ── Win32 message handling ──────────────────────────────────────────

    def nativeEvent(self, eventType, message):
        if sys.platform != "win32":
            return False, 0
        if eventType != b"windows_generic_MSG":
            return False, 0

        import ctypes
        from ctypes import wintypes
        msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents

        if msg.message == 0x0005:  # WM_SIZE
            # Throttle: restart the 33 ms timer.  If the user keeps
            # dragging, the timer never fires and we don't flood the
            # DWM with UpdateLayeredWindow calls.
            self._fill_timer.start(33)
        elif msg.message == 0x0232:  # WM_EXITSIZEMOVE
            # Resize gesture ended — stop the timer and paint immediately
            # so the final frame is guaranteed correct.
            self._fill_timer.stop()
            self._fill_layered()

        return False, 0

    # ── Per-pixel alpha surface update ───────────────────────────────────

    def _fill_layered(self):
        """Create (or reuse) a 32-bit BGRA DIB section, fill every pixel
        with ``(B=0, G=0, R=0, A=1)``, and submit it via
        ``UpdateLayeredWindow`` with ``ULW_ALPHA``."""
        import ctypes
        from ctypes import wintypes

        hwnd = int(self.winId())
        rect = wintypes.RECT()
        ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
        w, h = rect.right, rect.bottom
        if w <= 0 or h <= 0:
            return

        # ── Cached 32-bit DIB section (recreate only when growing) ──
        cache = getattr(self, '_ulw_cache', None)
        if cache is None or cache['w'] < w or cache['h'] < h:
            # Destroy previous cache if it exists
            if cache:
                ctypes.windll.gdi32.SelectObject(cache['dc'], cache['old'])
                ctypes.windll.gdi32.DeleteObject(cache['bmp'])
                ctypes.windll.gdi32.DeleteDC(cache['dc'])
                ctypes.windll.user32.ReleaseDC(0, cache['scrdc'])

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            bih = BITMAPINFOHEADER()
            bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bih.biWidth = w
            bih.biHeight = -h  # negative → top-down DIB (origin at top-left)
            bih.biPlanes = 1
            bih.biBitCount = 32  # BGRA, 8 bits per channel

            scrdc = ctypes.windll.user32.GetDC(0)
            mdc = ctypes.windll.gdi32.CreateCompatibleDC(scrdc)
            pBits = ctypes.c_void_p()
            hbmp = ctypes.windll.gdi32.CreateDIBSection(
                mdc, ctypes.byref(bih), 0, ctypes.byref(pBits), None, 0)
            old = ctypes.windll.gdi32.SelectObject(mdc, hbmp)
            self._ulw_cache = dict(dc=mdc, bmp=hbmp, pBits=pBits,
                                   old=old, scrdc=scrdc, w=w, h=h)
        else:
            mdc = cache['dc']
            scrdc = cache['scrdc']
            pBits = cache['pBits']

        # Fill: premultiplied alpha BGRA (B=0, G=0, R=0, A=1).
        # Uses Python bytes multiplication (C-level, no loop).
        ctypes.memmove(pBits, b'\x00\x00\x00\x01' * (w * h), w * h * 4)

        # BLENDFUNCTION: AC_SRC_OVER + AC_SRC_ALPHA.
        # SourceConstantAlpha=255 means "use per-pixel alpha as-is".
        # Fields MUST be ctypes.c_byte (signed), not wintypes.BYTE.
        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [
                ("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class SIZE(ctypes.Structure):
            _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

        blend = BLENDFUNCTION(0, 0, 255, 1)
        # pptDst=NULL — keep the window at its current screen position
        ctypes.windll.user32.UpdateLayeredWindow(
            hwnd, scrdc, None, ctypes.byref(SIZE(w, h)),
            mdc, ctypes.byref(POINT(0, 0)),
            0, ctypes.byref(blend), 0x00000002)  # 0x00000002 = ULW_ALPHA
