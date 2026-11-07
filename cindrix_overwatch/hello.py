"""Windows Hello (fingerprint, face or Windows PIN) as a way to unlock Watchtower. Only offered when this computer can do it.
Windows draws its own prompt. If anything goes wrong the Overwatch PIN is the way in."""

import os
import subprocess

NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_PRELUDE = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Security.Credentials.UI.UserConsentVerifier, Windows.Security.Credentials.UI, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
"""

AVAILABLE_SCRIPT = _PRELUDE + r"""
(Await ([Windows.Security.Credentials.UI.UserConsentVerifier]::CheckAvailabilityAsync()) ([Windows.Security.Credentials.UI.UserConsentVerifierAvailability])).ToString()
"""

VERIFY_SCRIPT = _PRELUDE + r"""
(Await ([Windows.Security.Credentials.UI.UserConsentVerifier]::RequestVerificationAsync('Unlock Watchtower')) ([Windows.Security.Credentials.UI.UserConsentVerificationResult])).ToString()
"""


def _run(script, timeout):
    if os.name != "nt":
        return ""
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
        return (r.stdout or "").strip().splitlines()[-1] if (r.stdout or "").strip() else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def available():
    """True when Windows Hello is set up on this computer."""
    return _run(AVAILABLE_SCRIPT, 20) == "Available"


def verify():
    """Shows the Windows prompt and returns True only when the person passed it. Blocks, so run it off the screen thread."""
    return _run(VERIFY_SCRIPT, 120) == "Verified"
