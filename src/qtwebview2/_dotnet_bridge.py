import threading
import typing

from . import exceptions
from .logger import logger
from .utils import get_absolute_path

dotnet_load_lock = threading.Lock()
dotnet_load_flag = False

if typing.TYPE_CHECKING:
    import System
    import System.Drawing
    import System.IO

    import Microsoft.Web.WebView2.Core
    import Microsoft.Web.WebView2.WinForms

    System_ = System
    Core = Microsoft.Web.WebView2.Core
    WinForms = Microsoft.Web.WebView2.WinForms

else:
    System_ = None
    Core = None
    WinForms = None


def load_dotnet_env(callback=None):
    global dotnet_load_flag

    global System_, Core, WinForms

    try:
        with dotnet_load_lock:
            if dotnet_load_flag:
                if callback:
                    callback()
                return
            logger.debug("Loading .NET environment for WebView2.", stack_info=True)

            import clr

            clr.AddReference('System')
            clr.AddReference('System.IO')
            clr.AddReference('System.Drawing')
            import System
            import System.Drawing
            import System.IO
            import System.Runtime.InteropServices

            # Add .NET library references required by WebView2
            clr.AddReference(get_absolute_path('lib/Microsoft.Web.WebView2.WinForms'))
            clr.AddReference(get_absolute_path('lib/Microsoft.Web.WebView2.Core'))
            import Microsoft.Web.WebView2.Core
            import Microsoft.Web.WebView2.WinForms

            System_ = System
            Core = Microsoft.Web.WebView2.Core
            WinForms = Microsoft.Web.WebView2.WinForms

            dotnet_load_flag = True

    except Exception as e:
        # Log detailed information for developers
        logger.critical("Critical Error: Failed to initialize .NET environment for WebView2.", exc_info=True)

        # Raise an exception
        raise exceptions.WebviewInitException(
            "Critical Error: Failed to initialize .NET environment for WebView2."
        ) from e

    logger.debug("Loaded .NET environment for WebView2.")
    if callback:
        callback()
