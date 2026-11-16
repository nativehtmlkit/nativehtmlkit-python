"""NativeHTMLKit: native HTML/CSS desktop windows controlled from Python.

Start an application from a normal script with ``Application.start()``; the
packaged Rust host owns the windows, rendering and event loop.
"""
from .application import Application, Window, Document, Node, StaleDocumentError
from .client import RpcClient, RpcError, ProtocolError, DisconnectedError
from ._bootstrap import StartupError
from .live_bitmap import LiveBitmap
from .launcher import host_binary

__version__ = "0.1.1"
__all__ = ["Application", "Window", "Document", "Node", "StaleDocumentError", "StartupError",
           "RpcClient", "RpcError", "ProtocolError", "DisconnectedError", "LiveBitmap", "host_binary"]

from .asyncio_api import AsyncApplication, AsyncRpcClient, EventDispatcher
from .errors import NativeHTMLKitError, RpcTimeoutError, HostProtocolError, HostDisconnectedError
from .diagnostics import SESSION_ID as diagnostics_session_id, export_bundle as export_support_bundle
__all__ += ["AsyncApplication", "AsyncRpcClient", "EventDispatcher", "NativeHTMLKitError", "RpcTimeoutError", "HostProtocolError", "HostDisconnectedError", "diagnostics_session_id", "export_support_bundle"]
