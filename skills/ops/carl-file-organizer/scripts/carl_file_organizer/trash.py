"""Move things to the system trash, or refuse; never fall back to deleting.

macOS goes through Finder, Linux through ``gio``, Windows through the shell's
own recycle bin call.  When none of them is available the backend is ``none``
and every trash request raises :class:`TrashError`, which is the whole point: a
failed trash must never quietly turn into a permanent delete.

The three backends are not symmetric.  Finder and gio are ordinary commands, so
they run through :func:`subprocess.run` and take the ``runner`` seam.  Windows
has no command that reliably reaches the recycle bin, so it calls
``SHFileOperationW`` through ctypes and takes the ``win_runner`` seam instead.
Both seams exist for the same reason: this module has to be testable on a
machine that is not the one being tested for.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional

FINDER = "finder"
GIO = "gio"
WINDOWS = "win32"
NONE = "none"

DEFAULT_TIMEOUT_S = 30.0

#: AppleScript error raised when the terminal is not allowed to drive Finder.
AUTOMATION_DENIED = "-1743"

MESSAGES = {
    "no_backend": {
        "zh": "这台机器没有可用的废纸篓后端，拒绝处置：{path}",
        "en": "No trash backend on this machine; refusing to dispose of {path}",
    },
    "still_there": {
        "zh": "废纸篓命令跑完了，但 {path} 还在原地，当作失败处理",
        "en": "The trash command finished but {path} is still there; treating it as a failure",
    },
    "automation_denied": {
        "zh": (
            "Finder 拒绝了自动化请求（-1743）。去系统设置 > 隐私与安全性 > 自动化，"
            "把终端对 Finder 的开关打开，再跑一次。"
        ),
        "en": (
            "Finder refused the automation request (-1743). Open System Settings > "
            "Privacy & Security > Automation and allow your terminal to control Finder, "
            "then run this again."
        ),
    },
    "failed": {
        "zh": "废纸篓命令失败（退出码 {code}）：{detail}",
        "en": "The trash command failed (exit code {code}): {detail}",
    },
    "windows_unavailable": {
        "zh": "这台 Windows 上调不到回收站接口（shell32），拒绝处置：{path}",
        "en": "The recycle bin interface (shell32) is unreachable on this Windows; refusing to dispose of {path}",
    },
    "windows_failed": {
        "zh": "回收站调用失败（SHFileOperationW 返回 {code}）",
        "en": "The recycle bin call failed (SHFileOperationW returned {code})",
    },
    "windows_aborted": {
        "zh": "回收站调用被中止，条目留在原地",
        "en": "The recycle bin call was aborted; the item stayed where it was",
    },
    "timeout": {
        "zh": "废纸篓命令超时（{seconds} 秒），可能有确认框在等你点",
        "en": "The trash command timed out after {seconds}s; a confirmation dialog may be waiting",
    },
}


class TrashError(RuntimeError):
    """The item did not reach the trash.  Nothing else is attempted."""


def message(key: str, lang: str = "en", **kw: Any) -> str:
    entry = MESSAGES.get(key, {})
    template = entry.get(lang) or entry.get("en") or key
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        return template


def detect_backend() -> str:
    """``finder`` on macOS, ``win32`` on Windows, ``gio`` elsewhere, else ``none``."""

    if sys.platform == "darwin" and shutil.which("osascript"):
        return FINDER
    if sys.platform == "win32":
        return WINDOWS if windows_available() else NONE
    if shutil.which("gio"):
        return GIO
    return NONE


def applescript_quote(text: str) -> str:
    """Escape a path for an AppleScript string literal (backslash first)."""

    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def finder_command(path: Path) -> List[str]:
    """The exact argv used for the Finder backend; never handed to a shell."""

    absolute = os.path.abspath(str(path))
    script = 'tell application "Finder" to delete POSIX file "{0}"'.format(
        applescript_quote(absolute)
    )
    return ["osascript", "-e", script]


def gio_command(path: Path) -> List[str]:
    return ["gio", "trash", "--", os.path.abspath(str(path))]


# ---------------------------------------------------------------------------
# Windows: the recycle bin through SHFileOperationW
# ---------------------------------------------------------------------------

#: ``FO_DELETE``: the operation itself.
FO_DELETE = 0x0003

#: Send it to the recycle bin rather than unlinking it.  Without this one flag
#: the very same call is a permanent delete, which is the outcome this whole
#: module exists to prevent, so it is never optional.
FOF_ALLOWUNDO = 0x0040

#: Do not put a yes/no dialog in front of a script that nobody is watching.
FOF_NOCONFIRMATION = 0x0010

#: No progress window.
FOF_SILENT = 0x0004

#: No modal error box either.  A dialog nobody can click would hang the process
#: forever, and the return code already tells us everything the box would say.
FOF_NOERRORUI = 0x0400

#: The exact flag word this tool uses.  One constant, so a reviewer can read the
#: policy in one line instead of reassembling it from call sites.
WINDOWS_FLAGS = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI


def windows_path_argument(path: Path) -> str:
    """The ``pFrom`` string: one absolute path, terminated by two NULs.

    ``SHFileOperationW`` reads a list of paths separated by NUL and ended by an
    empty entry, so a single path still needs the second NUL.  Building it here
    rather than at the call site means the shape is testable on any platform.
    """

    return os.path.abspath(str(path)) + "\0\0"


def windows_available() -> bool:
    """True when ``shell32`` can actually be reached from this interpreter."""

    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return ctypes.windll.shell32 is not None  # type: ignore[attr-defined]
    except (ImportError, AttributeError, OSError):
        return False


def windows_send_to_recycle_bin(path: Path) -> Any:
    """Call ``SHFileOperationW`` for one path; return ``(code, aborted)``.

    Nothing here is imported until it is called, so the module still imports
    cleanly on macOS and Linux, where ``ctypes.wintypes`` does not exist.
    """

    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    operation = SHFILEOPSTRUCTW()
    operation.hwnd = None
    operation.wFunc = FO_DELETE
    operation.pFrom = windows_path_argument(path)
    operation.pTo = None
    operation.fFlags = WINDOWS_FLAGS
    operation.fAnyOperationsAborted = False
    operation.hNameMappings = None
    operation.lpszProgressTitle = None

    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
    shell32.SHFileOperationW.restype = ctypes.c_int
    code = int(shell32.SHFileOperationW(ctypes.byref(operation)))
    return code, bool(operation.fAnyOperationsAborted)


def _windows_trash(
    target: Path,
    lang: str,
    win_runner: Optional[Callable[[Path], Any]],
) -> None:
    call = win_runner if win_runner is not None else windows_send_to_recycle_bin
    if win_runner is None and not windows_available():
        raise TrashError(message("windows_unavailable", lang, path=target))
    try:
        code, aborted = call(target)
    except OSError as error:
        raise TrashError(str(error)) from error
    if int(code) != 0:
        raise TrashError(message("windows_failed", lang, code=int(code)))
    if aborted:
        raise TrashError(message("windows_aborted", lang))


def move_to_trash(
    path: Path,
    *,
    backend: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    runner: Optional[Callable[..., Any]] = None,
    win_runner: Optional[Callable[[Path], Any]] = None,
    lang: str = "en",
) -> None:
    """Send one item to the trash or raise; there is no third outcome."""

    target = Path(path)
    if backend not in (FINDER, GIO, WINDOWS):
        raise TrashError(message("no_backend", lang, path=target))

    if backend == WINDOWS:
        _windows_trash(target, lang, win_runner)
        if os.path.lexists(str(target)):
            raise TrashError(message("still_there", lang, path=target))
        return

    argv = finder_command(target) if backend == FINDER else gio_command(target)
    call = runner if runner is not None else subprocess.run

    try:
        result = call(argv, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as error:
        raise TrashError(message("timeout", lang, seconds=timeout_s)) from error
    except OSError as error:
        raise TrashError(str(error)) from error

    code = int(getattr(result, "returncode", 0) or 0)
    stderr = (getattr(result, "stderr", "") or "").strip()
    if code != 0:
        if AUTOMATION_DENIED in stderr:
            raise TrashError(message("automation_denied", lang))
        raise TrashError(message("failed", lang, code=code, detail=stderr or "no output"))

    if os.path.lexists(str(target)):
        raise TrashError(message("still_there", lang, path=target))
