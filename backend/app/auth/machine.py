"""The machine this process runs on, and the Windows account it runs under: what sign-in matches a user's registration
against (app.auth.service), and what a job records as the host that queued it."""
import getpass
import os
import socket


def hostname() -> str:
    """This machine's name, as Windows reports it (COMPUTERNAME), else as the network stack does."""
    return (os.environ.get("COMPUTERNAME") or socket.gethostname()).strip()


def windows_account() -> str:
    """DOMAIN\\user of this process: from Windows itself (GetUserNameExW, NameSamCompatible), else from the
    environment, else the plain user name."""
    if os.name == "nt":
        try:
            import ctypes

            size = ctypes.c_ulong(0)
            secur32 = ctypes.WinDLL("secur32")
            secur32.GetUserNameExW(2, None, ctypes.byref(size))
            buffer = ctypes.create_unicode_buffer(size.value + 1)
            if secur32.GetUserNameExW(2, buffer, ctypes.byref(size)) and buffer.value:
                return buffer.value
        except (OSError, AttributeError):
            pass
    domain, user = os.environ.get("USERDOMAIN"), os.environ.get("USERNAME")
    if domain and user:
        return f"{domain}\\{user}"
    return getpass.getuser()


def same(a: str | None, b: str | None) -> bool:
    """Windows names compare without regard to case."""
    return (a or "").strip().lower() == (b or "").strip().lower()
