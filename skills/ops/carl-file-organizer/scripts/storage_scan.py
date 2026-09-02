#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整机只读盘点扫描器（macOS + Windows）。

它只做两件事：给这台机器拍一张体检照，再把最占地方的那些目录按组量出来，
写成一份 storage-scan.json 交给 Agent 去读。它不移动、不删除、不改权限，
连一个文件的内容都不打开，只看 stat 里的大小和时间。

用法：

    python3 storage_scan.py [--out storage-scan.json] [--budget-seconds 60]
                            [--top-files 30] [--home PATH]

尺寸口径：目录体积等于其下所有文件 st_size 之和，也就是逻辑大小。跟 du 的
块大小口径会有出入，稀疏文件和 APFS 压缩过的文件会偏大。要的是量级判断，
不是审计账。

预算口径：--budget-seconds 是整轮硬上限，按组、按条目层层分摊。到点就停，
量到一半的条目带 partial=True，顶层 budget_hit=True。宁可标不准，不报假数。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

SCHEMA = "storage-scan/1"

DEFAULT_BUDGET_SECONDS = 60.0
DEFAULT_TOP_FILES = 30
DEFAULT_MIN_FILE_MB = 200        # 进 top_files 的门槛
DEFAULT_MIN_SIZE_MB = 50         # 进 groups 的门槛，比它小的条目不进输出
SUBPROCESS_TIMEOUT = 5.0         # 每个体检子进程的硬超时
MAX_ENTRIES_PER_ITEM = 400000    # 单个条目最多遍历的目录项数
MEMO_MAX_DEPTH = 5               # 只缓存浅层目录体积，避免吃内存
TIME_CHECK_EVERY = 128           # 每遍历多少项看一次表

# 有些组天生就没那么大，用全局门槛会把它们全滤没。安装包尤其明显。
GROUP_MIN_SIZE_OVERRIDE = {
    "downloads_installers": 10 * 1024 * 1024,
    "trash": 1024 * 1024,
    "recycle_bin": 1024 * 1024,
}

GB = 1024 ** 3

# ---------------------------------------------------------------- 卷的取舍

#: macOS 的 df 会把一台机器的全部卷都摊出来：只读的系统卷、Preboot、VM、
#: Recovery、每个挂上来的磁盘镜像。它们跟人要腾的空间没关系，列出来只会把
#: 真正该看的那一行淹掉。所以磁盘列表只留两种卷：装着用户数据的那一个，和
#: 真外接上来的盘。其余的收进 system_volumes 里存个底，不进正文。
PRIMARY_DATA_MOUNT = "/System/Volumes/Data"
PRIMARY_DATA_NAME = "Macintosh HD 数据卷"
EXTERNAL_MOUNT_PREFIX = "/Volumes/"

#: 名字长这样的都是系统自己的卷或者本地快照，哪怕挂在 /Volumes 下也不算外接盘。
SYSTEM_VOLUME_NAMES = (
    "com.apple.timemachine",
    "recovery",
    "preboot",
    "vm",
    "update",
    "xarts",
    "iscpreboot",
    "hardware",
)

#: 比这还小的挂载点不是能放东西的盘，是脚本挂上来的临时镜像或者 RAM 盘。
#: 真的外接盘没有小于 1 GiB 的，所以这条门槛只会误伤假挂载。
MIN_EXTERNAL_VOLUME_BYTES = GB

# ---------------------------------------------------------------- 分类词表

REGENERABLE_DIR_NAMES = (
    "node_modules", ".next", "dist", "build", "target", "coverage",
    "__pycache__", ".turbo", ".nuxt", ".svelte-kit", ".parcel-cache",
)

INSTALLER_EXTS = (
    ".dmg", ".pkg", ".zip", ".iso", ".exe", ".msi", ".msix", ".appimage",
    ".deb", ".rpm", ".xip",
)

MEDIA_EXTS = (
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mp3", ".wav", ".aiff",
    ".flac", ".png", ".jpg", ".jpeg", ".heic", ".gif", ".tiff", ".psd", ".ai",
    ".sketch", ".fig", ".key", ".pptx",
)

# 命中即 dev_cache。写成路径段序列，小写、正斜杠。
DEV_CACHE_PATHS = (
    ".npm", ".pnpm-store", ".yarn", ".cargo", ".gradle", ".m2", ".nuget",
    ".cache", ".bun", ".deno", "go/pkg", "go-build",
    "library/caches/pip", "library/caches/uv", "library/caches/ms-playwright",
    "library/caches/homebrew", "library/caches/com.apple.dt.xcode",
    "library/developer/xcode/deriveddata",
    "library/developer/xcode/archives",
    "library/developer/xcode/ios devicesupport",
    "library/developer/coresimulator",
    "appdata/local/pip/cache", "appdata/local/npm-cache",
    "appdata/local/yarn", "appdata/local/nuget", "appdata/local/uv",
    "appdata/local/ms-playwright", "appdata/local/temp",
    "appdata/local/go-build", "appdata/local/microsoft/vscode",
)

# 禁刀区。删了要么丢账号、要么丢聊天记录、要么丢一整个库。
RED_PATHS = (
    "vm_bundles", "virtual machines", "parallels", "hyper-v",
    "docker-desktop-data", "wsl", "user data", "profiles",
    "library/safari",
    "library/application support/google/chrome",
    "library/application support/chromium",
    "library/application support/firefox",
    "library/application support/bravesoftware",
    "library/application support/microsoft edge",
    "library/keychains", "library/messages", "library/mail",
    "library/mobile documents", "library/calendars", "library/contacts",
    "library/containers/com.apple.mail",
    "library/containers/com.apple.messages",
    "library/group containers/group.com.apple.notes",
    "com.apple.photos", ".git", ".obsidian", "onedrive", "dropbox",
    "icloud drive", "appdata/roaming/microsoft/crypto",
    "appdata/local/microsoft/edge/user data",
    "appdata/local/google/chrome/user data",
    "appdata/roaming/mozilla/firefox/profiles",
)

# 目录名以这些结尾的一律 red。
RED_SUFFIXES = (
    ".photoslibrary", ".utm", ".pvm", ".vmwarevm", ".sparsebundle",
    ".musiclibrary", ".tvlibrary", ".imovielibrary", ".fcpbundle",
)

# 遍历时撞见这些目录名，就说明条目里面埋着禁刀区，整体不能当删除单元。
# 名字必须足够特异：messages、mail、profiles、.git 这种词随便哪个代码库里
# 都有，拿来下沉会把 Downloads、Documents、projects 一起染红，三色就废了。
RED_DIR_NAMES = frozenset((
    "vm_bundles", "user data", "virtual machines", "hyper-v",
    "docker-desktop-data",
))

# 这些只作提示，不改颜色：值得 Agent 知道，但不足以判整个条目死刑。
NOTABLE_DIR_NAMES = frozenset((
    ".git", ".obsidian", "keychains", "messages", "mail", "profiles",
))

CACHE_SEGMENTS = ("caches", "cache", "temp", "tmp", ".trash", "$recycle.bin")

APP_DATA_SEGMENTS = ("application support", "containers", "group containers",
                     "appdata")

MEDIA_SEGMENTS = ("movies", "music", "pictures")

WORKSPACE_CANDIDATES = (
    "projects", "agent-workbench", "workspace", "work", "worktrees",
    "dev", "src", "code", "repos", "Developer",
)

# ---------------------------------------------------------------- 小工具


def human(num_bytes):
    """字节数转成人能念出来的字符串。"""
    if num_bytes is None:
        return "?"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(value) < 1024.0 or unit == "PB":
            if unit == "B":
                return "%d B" % int(value)
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return "%.1f PB" % value


def iso_time(timestamp):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    except Exception:
        return None


def run_cmd(args, timeout=SUBPROCESS_TIMEOUT):
    """跑一个只读命令。超时、没这个命令、报错，都当没采到。"""
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except Exception:
        return ""
    try:
        return proc.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def path_segments(path):
    """拆成小写路径段，正反斜杠都认。"""
    return [seg for seg in path.replace("\\", "/").lower().split("/") if seg]


def haystack(path):
    """给段序列匹配用的干草堆，两头都带斜杠。"""
    return "/" + "/".join(path_segments(path)) + "/"


def matches_any(path, needles):
    """路径里是否出现过这些段序列之一。按段匹配，.git 不会命中 .gitignore。"""
    hay = haystack(path)
    for needle in needles:
        if ("/" + needle.strip("/") + "/") in hay:
            return True
    return False


def _windows_drive_letters():
    """列出 Windows 上所有盘符。测试里会把这个函数整体换掉。"""
    try:
        import ctypes

        bitmask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    except Exception:
        return []
    return [chr(ord("A") + i) for i in range(26) if bitmask >> i & 1]


# ---------------------------------------------------------------- 扫描器


class StorageScanner(object):
    """只读扫描器，一个实例负责一轮扫描。"""

    def __init__(
        self,
        home=None,
        platform_name=None,
        budget_seconds=DEFAULT_BUDGET_SECONDS,
        top_files=DEFAULT_TOP_FILES,
        min_file_bytes=DEFAULT_MIN_FILE_MB * 1024 * 1024,
        min_size_bytes=DEFAULT_MIN_SIZE_MB * 1024 * 1024,
        with_system=True,
    ):
        self.platform = platform_name or sys.platform
        self.is_windows = self.platform.startswith("win")
        default_home = os.environ.get(
            "USERPROFILE" if self.is_windows else "HOME"
        ) or os.path.expanduser("~")
        self.home = os.path.abspath(home or default_home)
        self.budget_seconds = float(budget_seconds)
        self.top_files_limit = int(top_files)
        self.min_file_bytes = int(min_file_bytes)
        self.min_size_bytes = int(min_size_bytes)
        self.with_system = with_system

        self.started_monotonic = time.monotonic()
        self.deadline = self.started_monotonic + self.budget_seconds
        self.budget_hit = False

        self._memo = {}
        self._memo_red = {}
        self._denied = {}
        self._big_files = {}
        self._entries_this_item = 0
        self._red_inside = []
        self._notable_inside = []
        self._tick = 0
        self._abort = False
        self.dropped_small = 0
        self._system_volumes = []

    # -------------------------------------------------- 路径

    @property
    def home_token(self):
        return "%USERPROFILE%" if self.is_windows else "$HOME"

    @property
    def sep(self):
        return "\\" if self.is_windows else "/"

    def join(self, *parts):
        return os.path.join(*parts)

    def portable(self, path):
        """绝对路径写成 $HOME/... 或 %USERPROFILE%\\...，不落用户名。"""
        try:
            rel = os.path.relpath(path, self.home)
        except ValueError:
            return path
        if rel == os.curdir:
            return self.home_token
        if rel == os.pardir or rel.startswith(os.pardir + os.sep):
            return path
        return self.home_token + self.sep + rel.replace(os.sep, self.sep)

    def scoped(self, path):
        """分类只看 home 以下的那一段。

        词表里的每一条都是从 home 数起的：``library/caches/pip``、
        ``appdata/local/temp``、``.trash``。可 home 上面还有别的目录名，而它
        们不该说话——一个 home 造在 ``/tmp`` 底下，整台机器就会因为路径里有
        一个 ``tmp`` 段被判成缓存，三色一起塌成 green。所以匹配前先把 home
        之上的部分减掉。home 以外的路径（外接盘、系统目录）原样返回，那里
        本来就没有 home 相对口径可言。
        """
        try:
            rel = os.path.relpath(path, self.home)
        except ValueError:
            return path
        if rel == os.curdir:
            return ""
        if rel == os.pardir or rel.startswith(os.pardir + os.sep):
            return path
        return rel.replace(os.sep, "/").replace("\\", "/")

    # -------------------------------------------------- 预算

    def time_left(self):
        return self.deadline - time.monotonic()

    def out_of_time(self):
        if self.time_left() <= 0:
            self.budget_hit = True
            return True
        return False

    def slice_deadline(self, share_of_remaining):
        """给一段工作切一块时间，最少 0.3 秒。"""
        remaining = max(self.time_left(), 0.0)
        return time.monotonic() + max(remaining * share_of_remaining, 0.3)

    # -------------------------------------------------- 遍历

    def note_denied(self, path, reason, counted_bytes=0):
        if path in self._denied:
            return
        self._denied[path] = {
            "path": path,
            "path_portable": self.portable(path),
            "reason": reason,
            "counted_bytes": counted_bytes,
        }

    def note_big_file(self, path, size, mtime):
        if size < self.min_file_bytes or path in self._big_files:
            return
        self._big_files[path] = {
            "path": path,
            "path_portable": self.portable(path),
            "name": os.path.basename(path),
            "size_bytes": size,
            "size_human": human(size),
            "mtime": mtime,
            "kind": self.guess_kind(path, is_dir=False),
        }

    @staticmethod
    def dir_marker(name):
        """这个目录名是禁刀区标志物（red），还是只值得一提（note）。"""
        low = name.lower()
        if low in RED_DIR_NAMES:
            return ("red", low)
        for suffix in RED_SUFFIXES:
            if low.endswith(suffix):
                return ("red", low)
        if low in NOTABLE_DIR_NAMES:
            return ("note", low)
        return None

    def walk_size(self, path, deadline, depth=0):
        """递归量一个目录，返回 (bytes, partial, marks)。只读，不跟 symlink。

        marks 是一串 (severity, name)，记下这棵树里埋着什么值得注意的东西。
        """
        memoized = self._memo.get(path)
        if memoized is not None:
            return memoized, False, self._memo_red.get(path, frozenset())

        total = 0
        partial = False
        marks = set()
        try:
            iterator = os.scandir(path)
        except PermissionError:
            self.note_denied(path, "permission_denied")
            return 0, True, marks
        except OSError as exc:
            self.note_denied(path, "os_error:" + exc.__class__.__name__)
            return 0, True, marks

        try:
            with iterator as entries:
                for entry in entries:
                    # 超时是全栈的：一层喊停，所有祖先层立刻跟着停，
                    # 否则每一层都要再攒够一轮才轮到看表，越深漂得越远。
                    if self._abort:
                        partial = True
                        break
                    self._entries_this_item += 1
                    self._tick += 1
                    if self._tick % TIME_CHECK_EVERY == 0 and time.monotonic() > deadline:
                        self._abort = True
                        partial = True
                        break
                    if self._entries_this_item > MAX_ENTRIES_PER_ITEM:
                        self._abort = True
                        partial = True
                        break
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            marker = self.dir_marker(entry.name)
                            if marker and len(marks) < 12:
                                marks.add(marker)
                            sub, sub_partial, sub_marks = self.walk_size(
                                entry.path, deadline, depth + 1
                            )
                            total += sub
                            partial = partial or sub_partial
                            if sub_marks and len(marks) < 12:
                                marks.update(sub_marks)
                        else:
                            stat = entry.stat(follow_symlinks=False)
                            total += stat.st_size
                            if stat.st_size >= self.min_file_bytes:
                                self.note_big_file(
                                    entry.path, stat.st_size, iso_time(stat.st_mtime)
                                )
                    except PermissionError:
                        self.note_denied(entry.path, "permission_denied")
                        partial = True
                    except OSError:
                        continue
        except PermissionError:
            self.note_denied(path, "permission_denied", total)
            partial = True
        except OSError:
            partial = True

        if not partial and depth <= MEMO_MAX_DEPTH:
            self._memo[path] = total
            self._memo_red[path] = frozenset(marks)
        return total, partial, marks

    def measure(self, path, deadline):
        """量一个路径：目录递归，文件 stat。返回 (bytes, partial, mtime)。"""
        self._entries_this_item = 0
        self._red_inside = []
        self._notable_inside = []
        self._abort = False
        try:
            stat = os.stat(path)
        except PermissionError:
            self.note_denied(path, "permission_denied")
            return None, True, None
        except OSError:
            return None, False, None
        mtime = iso_time(stat.st_mtime)
        if os.path.isdir(path):
            size, partial, marks = self.walk_size(path, deadline)
            self._red_inside = sorted(n for sev, n in marks if sev == "red")
            self._notable_inside = sorted(n for sev, n in marks if sev == "note")
            return size, partial, mtime
        self.note_big_file(path, stat.st_size, mtime)
        return stat.st_size, False, mtime

    # -------------------------------------------------- 分类

    def guess_kind(self, path, is_dir=True):
        inside = self.scoped(path)
        segs = path_segments(inside)
        name = segs[-1] if segs else ""

        if is_dir and name in REGENERABLE_DIR_NAMES:
            return "build_artifact"
        if matches_any(inside, DEV_CACHE_PATHS):
            return "dev_cache"
        if not is_dir:
            for ext in INSTALLER_EXTS:
                if name.endswith(ext):
                    return "installer"
            for ext in MEDIA_EXTS:
                if name.endswith(ext):
                    return "media"
        for seg in CACHE_SEGMENTS:
            if seg in segs:
                return "cache"
        for seg in APP_DATA_SEGMENTS:
            if seg in segs:
                return "app_data"
        for seg in MEDIA_SEGMENTS:
            if seg in segs:
                return "media"
        for workspace in WORKSPACE_CANDIDATES:
            if workspace.lower() in segs:
                return "project"
        if is_dir:
            try:
                if os.path.isdir(os.path.join(path, ".git")):
                    return "project"
            except OSError:
                pass
        return "unknown"

    def is_red(self, path):
        inside = self.scoped(path)
        for seg in path_segments(inside):
            for suffix in RED_SUFFIXES:
                if seg.endswith(suffix):
                    return True
        if matches_any(inside, RED_PATHS):
            return True
        # 目录里有 .obsidian 就是知识库主库，别碰。
        try:
            if os.path.isdir(os.path.join(path, ".obsidian")):
                return True
        except OSError:
            pass
        return False

    def suggest_color(self, path, kind, group, red_inside=()):
        """三色只是建议，最终解释权在 Agent 手里，但绿的门槛必须硬。

        判定顺序：自己在禁刀区就是 red；纯缓存和可再生产物是 green，哪怕里面
        混着一个叫 profiles 的目录也照样可再生；剩下的，里面埋着禁刀区的算
        red，其余一律 yellow，交给人看一眼。
        """
        if self.is_red(path):
            return "red"
        if group in ("trash", "recycle_bin"):
            return "green"
        if kind in ("cache", "dev_cache", "build_artifact"):
            return "green"
        if red_inside:
            return "red"
        return "yellow"

    def restore_hint(self, path, kind, group):
        name = (path_segments(path) or [""])[-1]
        if name == "node_modules":
            return "在项目根目录重跑 npm install / pnpm install / bun install"
        if name in (".next", "dist", "build", "target", ".turbo", "coverage"):
            return "重跑一次构建或 dev server 就会重新生成"
        if name == "__pycache__":
            return "下次导入模块时自动重建"
        if group in ("trash", "recycle_bin") or name in (".trash", "$recycle.bin"):
            return "清空之后不可恢复，先确认里面没有要留的东西"
        if kind == "dev_cache":
            return "下次装依赖或构建时会重新下载，第一次会慢一点"
        if kind == "cache":
            return "应用自己会重建，可能第一次启动稍慢"
        if kind == "installer":
            return "需要时去官网重新下载，老版本安装包一般不必留"
        if kind == "app_data":
            return "应用的账号、配置或本地数据，删了要重新登录或重新配置"
        if kind == "project":
            return "有远端仓库的可以重新 clone，没有的就是唯一副本"
        if kind == "media":
            return "素材本体，删了只能靠备份找回"
        return "没有自动恢复途径，动之前先确认别处有没有副本"

    def make_item(self, path, group, size, partial, mtime, is_dir=True):
        kind = self.guess_kind(path, is_dir=is_dir)
        red_inside = list(self._red_inside) if is_dir else []
        item = {
            "name": (path_segments(path) or [path])[-1],
            "path": path,
            "path_portable": self.portable(path),
            "size_bytes": size,
            "size_human": human(size),
            "kind": kind,
            "suggested_color": self.suggest_color(path, kind, group, red_inside),
            "restore_hint": self.restore_hint(path, kind, group),
            "mtime": mtime,
            "group": group,
            "partial": bool(partial),
        }
        if item["suggested_color"] == "red":
            if self.is_red(path):
                item["red_reason"] = "路径本身属于禁刀区"
            elif red_inside:
                item["red_reason"] = "里面埋着 " + "、".join(red_inside[:4])
        notable = list(self._notable_inside) if is_dir else []
        if notable:
            item["contains_notable"] = notable[:6]
        return item

    # -------------------------------------------------- 组

    def children_of(self, path):
        """一层子项，目录和文件都算，symlink 跳过。"""
        out = []
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                    except OSError:
                        continue
                    out.append(entry.path)
        except PermissionError:
            self.note_denied(path, "permission_denied")
        except OSError:
            pass
        return sorted(out)

    def installers_in(self, path):
        """Downloads 顶层的安装包，只看扩展名不进子目录。"""
        out = []
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink() or entry.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    low = entry.name.lower()
                    if any(low.endswith(ext) for ext in INSTALLER_EXTS):
                        out.append(entry.path)
        except PermissionError:
            self.note_denied(path, "permission_denied")
        except OSError:
            pass
        return sorted(out)

    def regenerable_under(self, roots, max_depth=3):
        """工作区下找可再生目录，命中即当叶子，不再往里走。"""
        found = []
        for root in roots:
            if not os.path.isdir(root):
                continue
            stack = [(root, 0)]
            while stack:
                if self.out_of_time():
                    return sorted(found)
                current, depth = stack.pop()
                try:
                    with os.scandir(current) as entries:
                        for entry in entries:
                            try:
                                if entry.is_symlink():
                                    continue
                                if not entry.is_dir(follow_symlinks=False):
                                    continue
                            except OSError:
                                continue
                            if entry.name in REGENERABLE_DIR_NAMES:
                                found.append(entry.path)
                                continue
                            if entry.name.startswith(".") or depth + 1 >= max_depth:
                                continue
                            stack.append((entry.path, depth + 1))
                except PermissionError:
                    self.note_denied(current, "permission_denied")
                except OSError:
                    continue
        return sorted(found)

    def group_specs(self):
        if self.is_windows:
            return self.windows_group_specs(self.home)
        return self.macos_group_specs(self.home)

    def macos_group_specs(self, home):
        """顺序是有讲究的：先量深层，再量浅层，浅层就能吃到 memo。"""
        library = self.join(home, "Library")
        return [
            ("dev_caches", [
                self.join(home, ".npm"),
                self.join(home, ".pnpm-store"),
                self.join(home, ".cache"),
                self.join(home, ".cargo"),
                self.join(home, ".gradle"),
                self.join(home, ".m2"),
                self.join(home, ".nuget"),
                self.join(home, ".bun"),
                self.join(home, "go", "pkg"),
                self.join(library, "Caches", "pip"),
                self.join(library, "Caches", "uv"),
                self.join(library, "Caches", "ms-playwright"),
                self.join(library, "Caches", "Homebrew"),
                self.join(library, "Caches", "com.apple.dt.Xcode"),
            ]),
            ("downloads_installers", ("installers", self.join(home, "Downloads"))),
            ("trash", [self.join(home, ".Trash")]),
            ("developer", [
                self.join(library, "Developer", "Xcode", "DerivedData"),
                self.join(library, "Developer", "Xcode", "Archives"),
                self.join(library, "Developer", "Xcode", "iOS DeviceSupport"),
                self.join(library, "Developer", "CoreSimulator"),
            ]),
            ("caches", ("children", self.join(library, "Caches"))),
            ("app_support", ("children", self.join(library, "Application Support"))),
            ("containers", ("children", self.join(library, "Containers"))),
            ("group_containers", ("children", self.join(library, "Group Containers"))),
            ("logs", ("children", self.join(library, "Logs"))),
            ("projects_regenerable", ("regenerable", [
                self.join(home, name) for name in WORKSPACE_CANDIDATES
            ])),
            ("library", ("children", library)),
            ("home_top", ("children", home)),
        ]

    def windows_group_specs(self, home):
        local = self.join(home, "AppData", "Local")
        roaming = self.join(home, "AppData", "Roaming")
        system_drive = os.environ.get("SystemDrive", "C:")
        return [
            ("dev_caches", [
                self.join(home, ".cache"),
                self.join(home, ".npm"),
                self.join(home, ".gradle"),
                self.join(home, ".m2"),
                self.join(home, ".nuget"),
                self.join(home, ".cargo"),
            ]),
            ("downloads_installers", ("installers", self.join(home, "Downloads"))),
            ("recycle_bin", [system_drive + "\\$Recycle.Bin"]),
            ("appdata_local", ("children_plus", (local, [
                self.join(local, "Temp"),
                self.join(local, "pip", "Cache"),
                self.join(local, "npm-cache"),
                self.join(local, "Yarn"),
                self.join(local, "NuGet"),
                self.join(local, "uv"),
                self.join(local, "ms-playwright"),
                self.join(local, "Google", "Chrome", "User Data"),
                self.join(local, "Microsoft", "Edge", "User Data"),
                self.join(local, "Mozilla", "Firefox", "Profiles"),
            ]))),
            ("appdata_roaming", ("children", roaming)),
            ("projects_regenerable", ("regenerable", [
                self.join(home, name) for name in WORKSPACE_CANDIDATES
            ])),
            ("user_top", ("children", home)),
        ]

    def resolve_spec(self, spec):
        """把组的声明解析成一串待测路径。"""
        if isinstance(spec, list):
            return [path for path in spec if os.path.exists(path)]
        mode, payload = spec
        if mode == "children":
            return self.children_of(payload)
        if mode == "children_plus":
            base, extras = payload
            paths = self.children_of(base)
            known = set(paths)
            for extra in extras:
                if extra not in known and os.path.exists(extra):
                    paths.append(extra)
            return sorted(paths)
        if mode == "installers":
            return self.installers_in(payload)
        if mode == "regenerable":
            return self.regenerable_under(payload)
        return []

    def scan_one_group(self, name, spec, group_deadline):
        paths = self.resolve_spec(spec)
        floor = self.min_size_bytes
        override = GROUP_MIN_SIZE_OVERRIDE.get(name)
        if override is not None:
            floor = min(floor, override)
        items = []
        for index, path in enumerate(paths):
            if os.path.islink(path):
                continue
            remaining_items = len(paths) - index
            now = time.monotonic()
            if now > group_deadline or self.out_of_time():
                self.budget_hit = True
                break
            share = max((group_deadline - now) / remaining_items, 0.3)
            item_deadline = min(now + share, self.deadline)
            is_dir = os.path.isdir(path)
            size, partial, mtime = self.measure(path, item_deadline)
            if size is None:
                continue
            if size < floor and not partial:
                self.dropped_small += 1
                continue
            items.append(self.make_item(path, name, size, partial, mtime, is_dir))
        items.sort(key=lambda entry: entry["size_bytes"], reverse=True)
        return items

    def scan_groups(self):
        specs = self.group_specs()
        groups = {}
        skipped = []
        for index, (name, spec) in enumerate(specs):
            if self.out_of_time():
                groups[name] = []
                skipped.append(name)
                continue
            remaining_groups = len(specs) - index
            group_deadline = self.slice_deadline(1.0 / remaining_groups)
            groups[name] = self.scan_one_group(name, spec, group_deadline)
        groups["system_notes"] = self.system_notes()
        return groups, skipped

    def system_notes(self):
        """只写不扫。这些地方要空间得走系统自己的路子，不能直接删。"""
        if self.is_windows:
            notes = [
                ("WinSxS 组件存储", "C:\\Windows\\WinSxS",
                 "系统组件的历史版本，看着大，里面大量是硬链接，直接删会让更新和修复失败。",
                 "管理员执行 DISM /Online /Cleanup-Image /StartComponentCleanup"),
                ("Windows 更新缓存", "C:\\Windows\\SoftwareDistribution\\Download",
                 "已下载的更新包，装完就没用了，但更新服务在跑的时候删会卡住。",
                 "用磁盘清理里的 Windows 更新清理，或先停 wuauserv 再清"),
                ("休眠文件 hiberfil.sys", "C:\\hiberfil.sys",
                 "内存镜像，通常跟物理内存一个量级，删掉等于关掉休眠和快速启动。",
                 "管理员执行 powercfg /hibernate off"),
                ("虚拟内存 pagefile.sys", "C:\\pagefile.sys",
                 "系统页面文件，直接删要么蓝屏要么立刻被重建。",
                 "在系统属性的虚拟内存里改大小或换盘"),
                ("系统还原点", "C:\\System Volume Information",
                 "还原点和卷影副本，占的是保留配额，资源管理器里看不到。",
                 "系统保护里调低磁盘使用比例，或删掉旧还原点"),
            ]
        else:
            notes = [
                ("可清除空间 Purgeable", "/System/Volumes/Data",
                 "系统标记为可清除的部分，df 里算在已用，磁盘紧张时系统会自己回收。",
                 "真的缺空间时自动释放，也可以在存储设置里查看"),
                ("时间机器本地快照", "/Volumes/com.apple.TimeMachine.localsnapshots",
                 "本地快照挂在系统卷上，用户目录里看不见，却实实在在占地方。",
                 "tmutil listlocalsnapshots / 由系统按空间压力自动回收"),
                ("系统级缓存", "/Library/Caches",
                 "全机共用的缓存，属于系统卷，普通用户改不动。",
                 "需要管理员权限，一般不建议手动清"),
            ]
        out = []
        for title, path, what, how in notes:
            out.append({
                "name": title,
                "path": path,
                "path_portable": path,
                "size_bytes": None,
                "size_human": "未测量",
                "kind": "system",
                "suggested_color": "red",
                "restore_hint": how,
                "mtime": None,
                "group": "system_notes",
                "partial": False,
                "scanned": False,
                "note": what,
            })
        return out

    # -------------------------------------------------- 体检

    def collect_disks(self):
        if self.is_windows:
            return self.collect_disks_windows()
        return self.collect_disks_macos()

    @staticmethod
    def volume_role(mount, total_bytes):
        """一个挂载点是 primary（数据卷）、external（外接盘），还是 system。"""
        if mount == PRIMARY_DATA_MOUNT:
            return "primary"
        if not mount.startswith(EXTERNAL_MOUNT_PREFIX):
            return "system"
        name = mount[len(EXTERNAL_MOUNT_PREFIX):].split("/")[0]
        low = name.lower()
        for marker in SYSTEM_VOLUME_NAMES:
            if low == marker or low.startswith(marker + "."):
                return "system"
        if total_bytes < MIN_EXTERNAL_VOLUME_BYTES:
            return "system"
        return "external"

    def collect_disks_macos(self):
        disks = []
        system_volumes = []
        output = run_cmd(["df", "-k"])
        for line in output.splitlines()[1:]:
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            device, blocks, used, avail, mount = (
                parts[0], parts[1], parts[2], parts[3], parts[8]
            )
            if not device.startswith("/dev/"):
                continue
            try:
                total_b = int(blocks) * 1024
                used_b = int(used) * 1024
                free_b = int(avail) * 1024
            except ValueError:
                continue
            role = self.volume_role(mount, total_b)
            disk = self.make_disk(
                mount, device, total_b, used_b, free_b, "df",
                name=PRIMARY_DATA_NAME if role == "primary" else None,
                primary=role == "primary",
            )
            if role == "system":
                system_volumes.append(disk)
            else:
                disks.append(disk)
        disks.sort(key=lambda entry: (not entry["primary"], entry["mount"]))
        self._system_volumes = system_volumes
        if not disks:
            fallback = self.fallback_disk("/")
            if fallback:
                disks.append(fallback)
        return disks

    def collect_disks_windows(self):
        disks = []
        for letter in _windows_drive_letters():
            root = letter + ":\\"
            try:
                total, used, free = shutil.disk_usage(root)
            except Exception:
                continue
            disks.append(
                self.make_disk(root, root, total, used, free, "shutil.disk_usage")
            )
        if not disks:
            fallback = self.fallback_disk(os.environ.get("SystemDrive", "C:") + "\\")
            if fallback:
                disks.append(fallback)
        return disks

    def fallback_disk(self, root):
        try:
            total, used, free = shutil.disk_usage(root)
        except Exception:
            return None
        return self.make_disk(root, root, total, used, free, "shutil.disk_usage")

    def make_disk(self, mount, device, total, used, free, source,
                  name=None, primary=False):
        capacity = 0.0
        if used + free > 0:
            capacity = round(100.0 * used / float(used + free), 1)
        flags = []
        if capacity >= 85.0:
            flags.append("high_usage")
        if free < 30 * GB:
            flags.append("low_free")
        return {
            "name": name or os.path.basename(mount.rstrip("/\\")) or mount,
            "primary": bool(primary),
            "mount": mount,
            "device": device,
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "total_human": human(total),
            "used_human": human(used),
            "free_human": human(free),
            "capacity_percent": capacity,
            "flags": flags,
            "source": source,
        }

    def collect_system_info(self):
        info = {
            "platform": self.platform,
            "home_token": self.home_token,
            "python": "%d.%d.%d" % sys.version_info[:3],
            "cpu_count": os.cpu_count(),
        }
        if self.is_windows:
            import platform as platform_mod

            info["os"] = platform_mod.system() + " " + platform_mod.release()
            info["os_build"] = platform_mod.version()
            info["arch"] = os.environ.get(
                "PROCESSOR_ARCHITECTURE", platform_mod.machine()
            )
            return info

        product = run_cmd(["sw_vers", "-productVersion"]).strip()
        if product:
            info["os"] = "macOS " + product
        build = run_cmd(["sw_vers", "-buildVersion"]).strip()
        if build:
            info["os_build"] = build
        arch = run_cmd(["uname", "-m"]).strip()
        if arch:
            info["arch"] = arch
        brand = run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        if brand:
            info["cpu"] = brand
        memsize = run_cmd(["sysctl", "-n", "hw.memsize"]).strip()
        if memsize.isdigit():
            info["memory_bytes"] = int(memsize)
            info["memory_human"] = human(int(memsize))
        pressure = run_cmd(["memory_pressure"])
        if pressure:
            info["memory_pressure_head"] = "\n".join(pressure.splitlines()[:8])
        vm_stat = run_cmd(["vm_stat"])
        if vm_stat:
            info["vm_stat_head"] = "\n".join(vm_stat.splitlines()[:6])
        uptime = run_cmd(["uptime"]).strip()
        if uptime:
            info["uptime"] = uptime
        return info

    # -------------------------------------------------- 汇总

    def top_files(self):
        files = sorted(
            self._big_files.values(),
            key=lambda entry: entry["size_bytes"],
            reverse=True,
        )
        return files[: self.top_files_limit]

    def run(self):
        if self.with_system:
            system = self.collect_system_info()
            disks = self.collect_disks()
        else:
            system = {"platform": self.platform, "home_token": self.home_token}
            disks = []

        groups, skipped = self.scan_groups()
        top = self.top_files()
        denied = sorted(self._denied.values(), key=lambda entry: entry["path"])

        measured = 0
        item_count = 0
        partial_count = 0
        for items in groups.values():
            for item in items:
                if item.get("size_bytes"):
                    measured += item["size_bytes"]
                item_count += 1
                if item.get("partial"):
                    partial_count += 1

        denied_note = ""
        if denied:
            denied_note = (
                "有 %d 个目录读不到，体积没有计入，实际占用比这份数字更大。"
                % len(denied)
            )

        return {
            "schema": SCHEMA,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "platform": self.platform,
            "home_token": self.home_token,
            "system": system,
            "disks": disks,
            "system_volumes": self._system_volumes,
            "groups": groups,
            "top_files": top,
            "denied": denied,
            "elapsed_seconds": round(time.monotonic() - self.started_monotonic, 2),
            "budget_seconds": self.budget_seconds,
            "budget_hit": self.budget_hit,
            "skipped_groups": skipped,
            "summary": {
                "group_count": len(groups),
                "item_count": item_count,
                "partial_item_count": partial_count,
                "measured_bytes": measured,
                "measured_human": human(measured),
                "sizes_are_lower_bounds": partial_count > 0,
                "partial_note": (
                    "有 %d 个条目没量完就到点了，它们的体积是下限，实际更大。"
                    % partial_count
                ) if partial_count else "",
                "dropped_below_floor": self.dropped_small,
                "min_size_bytes": self.min_size_bytes,
                "min_file_bytes": self.min_file_bytes,
                "denied_count": len(denied),
                "denied_note": denied_note,
            },
        }


# ---------------------------------------------------------------- 入口


def run_scan(**kwargs):
    """跑一轮扫描，返回 storage-scan.json 的内容（dict）。"""
    return StorageScanner(**kwargs).run()


def format_summary(data):
    lines = ["扫描用时 %.2fs%s" % (
        data["elapsed_seconds"], "，撞到预算上限" if data["budget_hit"] else ""
    )]
    for disk in data.get("disks", []):
        lines.append("盘 %s：%s 已用 / %s 可用 / %s%%" % (
            disk["mount"], disk["used_human"], disk["free_human"],
            disk["capacity_percent"],
        ))
    for name in sorted(data["groups"]):
        items = data["groups"][name]
        if items:
            lines.append("  %-22s %d 项" % (name, len(items)))
    top = data.get("top_files", [])[:5]
    if top:
        lines.append("最大的几个文件：")
        for entry in top:
            lines.append("  %10s  %s" % (entry["size_human"], entry["path_portable"]))
    for key in ("partial_note", "denied_note"):
        if data["summary"].get(key):
            lines.append(data["summary"][key])
    return "\n".join(lines)


def forgiving_console():
    """摘要里全是中文，而 Windows 上重定向出去的 stdout 是老代码页。

    不管它的话，一次量完的扫描会在打印摘要那一行抛 UnicodeEncodeError，
    盘点结果明明已经落盘了，退出码却是 1。JSON 自己带 encoding="utf-8"，
    从来不受影响；转义的只是给人看的那几行。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (ValueError, OSError):
            continue


def main(argv=None):
    forgiving_console()
    parser = argparse.ArgumentParser(
        description="整机只读盘点扫描（macOS + Windows），只量大小，不动文件。"
    )
    parser.add_argument("--out", default="storage-scan.json",
                        help="输出文件路径，写 - 就打到标准输出")
    parser.add_argument("--budget-seconds", type=float,
                        default=DEFAULT_BUDGET_SECONDS, help="整轮时间上限")
    parser.add_argument("--top-files", type=int, default=DEFAULT_TOP_FILES,
                        help="大文件榜取前几名")
    parser.add_argument("--min-file-mb", type=float, default=DEFAULT_MIN_FILE_MB,
                        help="进大文件榜的门槛，单位 MB")
    parser.add_argument("--min-size-mb", type=float, default=DEFAULT_MIN_SIZE_MB,
                        help="进分组清单的门槛，单位 MB")
    parser.add_argument("--home", default=None, help="指定要扫的家目录，默认当前用户")
    parser.add_argument("--quiet", action="store_true", help="不打人类可读摘要")
    args = parser.parse_args(argv)

    data = run_scan(
        home=args.home,
        budget_seconds=args.budget_seconds,
        top_files=args.top_files,
        min_file_bytes=int(args.min_file_mb * 1024 * 1024),
        min_size_bytes=int(args.min_size_mb * 1024 * 1024),
    )

    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out == "-":
        sys.stdout.write(payload + "\n")
    else:
        out_path = os.path.abspath(args.out)
        parent = os.path.dirname(out_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        if not args.quiet:
            sys.stdout.write("已写入 %s\n" % out_path)
    if not args.quiet:
        sys.stdout.write(format_summary(data) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
