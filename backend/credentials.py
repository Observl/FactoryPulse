"""Credential vault with current-Windows-user DPAPI fallback; never plaintext."""
import ctypes
import os
import tempfile
from pathlib import Path
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(value: bytes, decrypt=False) -> bytes:
    if os.name != "nt": raise OSError("Windows DPAPI unavailable")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    # UI_FORBIDDEN, current user scope; no machine-wide encryption flag.
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try: return ctypes.string_at(target.data, target.size)
    finally: kernel.LocalFree(target.data)


def encrypted_path(directory):
    return Path(directory) / "credentials" / "ai-key.dpapi"


def save_secret(directory, value):
    try:
        import keyring
        keyring.set_password("FactoryPulse", "ai-api-key", value)
        if keyring.get_password("FactoryPulse", "ai-api-key") == value:
            # Vault takes precedence only after a verified successful write.
            encrypted_path(directory).unlink(missing_ok=True)
            return True
    except Exception:
        pass
    temporary = None
    try:
        encrypted = _dpapi(value.encode("utf-8"))
        if _dpapi(encrypted, True).decode("utf-8") != value: return False
        path = encrypted_path(directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(encrypted)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        return True
    except (OSError, UnicodeError):
        return False
    finally:
        if temporary: temporary.unlink(missing_ok=True)


def load_secret(directory):
    # A DPAPI fallback can contain a more recent key than a stale vault entry.
    path = encrypted_path(directory)
    if path.exists():
        try: return _dpapi(path.read_bytes(), True).decode("utf-8")
        except (OSError, UnicodeError): return ""
    try:
        import keyring
        return keyring.get_password("FactoryPulse", "ai-api-key") or ""
    except Exception: return ""
