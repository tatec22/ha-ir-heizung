"""Lets the Home Assistant test harness run on Windows for local development.

Home Assistant imports two Unix-only modules at startup. On Windows they are
replaced by inert stand-ins and the harness plugin is loaded here; run pytest
with ``-p no:homeassistant`` there. CI on Linux uses the plugin unchanged.
"""

import sys
import types

if sys.platform == "win32":
    sys.modules.setdefault("fcntl", types.ModuleType("fcntl"))
    resource = types.ModuleType("resource")
    resource.RLIMIT_NOFILE = 7
    resource.getrlimit = lambda *_: (4096, 4096)
    resource.setrlimit = lambda *_: None
    sys.modules.setdefault("resource", resource)
    pytest_plugins = ["pytest_homeassistant_custom_component.plugins"]

    import pytest_socket

    # Windows event loops need a local socket pair for their self-pipe, which
    # the harness's socket guard would refuse.
    pytest_socket.disable_socket = lambda *args, **kwargs: None
    pytest_socket.socket_allow_hosts = lambda *args, **kwargs: None
