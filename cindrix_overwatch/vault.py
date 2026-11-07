"""Keeps camera logins and the phone-link code scrambled on disk. On Windows the scrambling key belongs to the signed-in user
(Windows' own protected storage), so the saved file is useless on another account or computer. Elsewhere (tests) text is left as it is."""

import base64
import os

PREFIX = "dpapi1:"


def _blob_call(data, protect):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buf = ctypes.create_string_buffer(data, len(data))
    src = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("Windows could not " + ("protect" if protect else "unprotect") + " the data")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def seal(text):
    if not text or os.name != "nt":
        return text
    try:
        return PREFIX + base64.b64encode(_blob_call(text.encode("utf-8"), True)).decode("ascii")
    except OSError:
        return text


def open_(stored):
    if not stored or not stored.startswith(PREFIX):
        return stored
    try:
        return _blob_call(base64.b64decode(stored[len(PREFIX):]), False).decode("utf-8")
    except (OSError, ValueError):
        return ""
