#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""carl-file-organizer 整机盘点扫描器的测试。

全部在临时目录里造假 home，通过 --home / home= 注入，不碰真实用户目录。
Windows 分支只验证分组路径拼接和 %USERPROFILE% 前缀，不真跑扫描。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "ops", "carl-file-organizer", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import storage_scan  # noqa: E402

MB = 1024 * 1024


def write_file(path, size_bytes=1024):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x" * size_bytes)


def write_sparse(path, size_bytes):
    """造一个逻辑大小够大、实际不占地方的稀疏文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.seek(size_bytes - 1)
        handle.write(b"\0")


def build_fake_home(home):
    library = os.path.join(home, "Library")
    # 纯缓存与开发缓存
    write_file(os.path.join(library, "Caches", "Homebrew", "bottle.tar"), 4096)
    write_file(os.path.join(library, "Caches", "com.example.App", "blob.bin"), 4096)
    write_file(os.path.join(home, ".npm", "_cacache", "index", "aa"), 4096)
    # 应用数据里埋一个禁刀区
    write_file(
        os.path.join(library, "Application Support", "DemoAgent",
                     "vm_bundles", "demo.bundle", "disk.img"),
        4096,
    )
    # 路径本身就在禁刀区
    write_file(os.path.join(library, "Messages", "chat.db"), 4096)
    # 可再生构建产物
    write_file(os.path.join(home, "projects", "x", "node_modules", "pkg", "i.js"), 4096)
    write_file(os.path.join(home, "projects", "x", ".next", "cache", "b.pack"), 4096)
    write_file(os.path.join(home, "projects", "x", "src", "main.py"), 512)
    # 安装包，外加两个通用名目录：它们不该把 Downloads 整个染红
    write_file(os.path.join(home, "Downloads", "SomeApp-1.2.3.dmg"), 8192)
    write_file(os.path.join(home, "Downloads", "notes.txt"), 128)
    write_file(os.path.join(home, "Downloads", "messages", "export.json"), 256)
    write_file(os.path.join(home, "Downloads", "some-repo", ".git", "config"), 256)
    # 废纸篓
    write_file(os.path.join(home, ".Trash", "junk.bin"), 4096)
    # 一个够大的稀疏文件，用来验大文件榜
    write_sparse(os.path.join(home, "Movies", "big-render.mov"), 210 * MB)


class StorageScanMacTest(unittest.TestCase):
    """macOS 分支：真的在假 home 上跑一遍。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cfo-scan-")
        cls.home = os.path.join(cls.tmp, "fakehome")
        os.makedirs(cls.home)
        build_fake_home(cls.home)
        cls.locked = os.path.join(cls.home, "locked-dir")
        os.makedirs(cls.locked)
        write_file(os.path.join(cls.locked, "secret.bin"), 2048)
        cls.locked_applied = False
        if os.geteuid() != 0:
            os.chmod(cls.locked, 0o000)
            cls.locked_applied = True
        cls.data = storage_scan.run_scan(
            home=cls.home,
            platform_name="darwin",
            budget_seconds=30,
            top_files=10,
            min_size_bytes=0,
            with_system=False,
        )

    @classmethod
    def tearDownClass(cls):
        if cls.locked_applied:
            os.chmod(cls.locked, 0o700)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def items(self, group):
        return self.data["groups"].get(group, [])

    def find(self, group, name):
        for item in self.items(group):
            if item["name"] == name.lower() or item["name"] == name:
                return item
        return None

    def test_schema_and_envelope(self):
        self.assertEqual(self.data["schema"], "storage-scan/1")
        self.assertEqual(self.data["platform"], "darwin")
        self.assertEqual(self.data["home_token"], "$HOME")
        for key in ("generated_at", "system", "disks", "groups", "top_files",
                    "denied", "elapsed_seconds", "budget_hit", "summary"):
            self.assertIn(key, self.data)
        self.assertFalse(self.data["budget_hit"])

    def test_expected_groups_present(self):
        expected = {
            "home_top", "library", "caches", "app_support", "containers",
            "group_containers", "logs", "developer", "dev_caches",
            "projects_regenerable", "downloads_installers", "trash",
            "system_notes",
        }
        self.assertTrue(expected.issubset(set(self.data["groups"])))

    def test_dev_cache_is_green(self):
        item = self.find("dev_caches", ".npm")
        self.assertIsNotNone(item, "dev_caches 里应该有 .npm")
        self.assertEqual(item["kind"], "dev_cache")
        self.assertEqual(item["suggested_color"], "green")
        self.assertTrue(item["restore_hint"])

    def test_cache_child_is_green(self):
        item = self.find("caches", "com.example.app")
        self.assertIsNotNone(item, "caches 一层子目录应该被量到")
        self.assertEqual(item["kind"], "cache")
        self.assertEqual(item["suggested_color"], "green")

    def test_build_artifacts_are_green(self):
        names = {item["name"] for item in self.items("projects_regenerable")}
        self.assertIn("node_modules", names)
        self.assertIn(".next", names)
        for item in self.items("projects_regenerable"):
            self.assertEqual(item["kind"], "build_artifact")
            self.assertEqual(item["suggested_color"], "green")
        node_modules = self.find("projects_regenerable", "node_modules")
        self.assertIn("install", node_modules["restore_hint"])

    def test_installer_is_yellow(self):
        items = self.items("downloads_installers")
        names = {item["name"] for item in items}
        self.assertIn("someapp-1.2.3.dmg", names)
        self.assertNotIn("notes.txt", names)
        for item in items:
            self.assertEqual(item["kind"], "installer")
            self.assertEqual(item["suggested_color"], "yellow")

    def test_trash_is_green(self):
        item = self.find("trash", ".trash")
        self.assertIsNotNone(item)
        self.assertEqual(item["suggested_color"], "green")

    def test_red_by_own_path(self):
        item = self.find("library", "messages")
        self.assertIsNotNone(item, "library 一层里应该有 Messages")
        self.assertEqual(item["suggested_color"], "red")
        self.assertIn("禁刀区", item["red_reason"])

    def test_red_by_buried_marker(self):
        item = self.find("app_support", "demoagent")
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], "app_data")
        self.assertEqual(item["suggested_color"], "red")
        self.assertIn("vm_bundles", item["red_reason"])

    def test_common_dir_names_do_not_turn_a_folder_red(self):
        """messages、.git 这种到处都有的名字不能把 Downloads 判死刑。

        真机第一次扫描时这条规则把 Downloads、Documents、projects 全染成了
        红色，三色直接失效，所以钉在这里防回归。
        """
        item = self.find("home_top", "downloads")
        self.assertIsNotNone(item)
        self.assertEqual(item["suggested_color"], "yellow")
        self.assertNotIn("red_reason", item)
        notable = item.get("contains_notable", [])
        self.assertIn("messages", notable)
        self.assertIn(".git", notable)

    def test_buried_vm_bundle_still_turns_parent_red(self):
        """特异标志物照样要能一路上浮到顶层条目。"""
        item = self.find("home_top", "library")
        self.assertIsNotNone(item)
        self.assertEqual(item["suggested_color"], "red")
        self.assertIn("vm_bundles", item["red_reason"])

    def test_top_files(self):
        top = self.data["top_files"]
        self.assertTrue(top, "210MB 的文件应该进大文件榜")
        first = top[0]
        self.assertEqual(first["name"], "big-render.mov")
        self.assertGreaterEqual(first["size_bytes"], 200 * MB)
        self.assertEqual(first["kind"], "media")
        self.assertTrue(first["path_portable"].startswith("$HOME/"))

    def test_paths_are_portable(self):
        for group, items in self.data["groups"].items():
            if group == "system_notes":
                continue
            for item in items:
                self.assertTrue(
                    item["path_portable"].startswith("$HOME/"),
                    "%s 的 path_portable 没有用 $HOME 前缀：%s"
                    % (group, item["path_portable"]),
                )
                self.assertTrue(os.path.isabs(item["path"]))

    def test_portable_fields_never_carry_the_real_home(self):
        """path 是给执行器用的真路径，path_portable 必须一个用户名都不带。"""
        portables = []
        for group, items in self.data["groups"].items():
            portables.extend(item["path_portable"] for item in items)
        portables.extend(item["path_portable"] for item in self.data["top_files"])
        portables.extend(item["path_portable"] for item in self.data["denied"])
        self.assertTrue(portables)
        for portable in portables:
            self.assertNotIn(self.home, portable)
            self.assertNotIn(self.tmp, portable)

    def test_trash_hint_survives_grouping(self):
        """废纸篓不管出现在哪个组，恢复提示都不能变成应用会自己重建。"""
        for group in ("trash", "home_top"):
            for item in self.items(group):
                if item["name"] == ".trash":
                    self.assertIn("不可恢复", item["restore_hint"])

    @unittest.skipIf(os.geteuid() == 0, "root 读得动 chmod 000 的目录")
    def test_denied_recorded(self):
        denied_paths = {entry["path"] for entry in self.data["denied"]}
        self.assertIn(self.locked, denied_paths)
        entry = [e for e in self.data["denied"] if e["path"] == self.locked][0]
        self.assertEqual(entry["reason"], "permission_denied")
        self.assertTrue(entry["path_portable"].startswith("$HOME/"))
        self.assertIn("读不到", self.data["summary"]["denied_note"])

    def test_system_notes_are_not_scanned(self):
        notes = self.data["groups"]["system_notes"]
        self.assertTrue(notes)
        for note in notes:
            self.assertIsNone(note["size_bytes"])
            self.assertFalse(note["scanned"])
            self.assertEqual(note["suggested_color"], "red")

    def test_min_size_floor_drops_small_items(self):
        data = storage_scan.run_scan(
            home=self.home,
            platform_name="darwin",
            budget_seconds=30,
            min_size_bytes=100 * MB,
            with_system=False,
        )
        self.assertEqual(data["groups"]["caches"], [])
        self.assertGreater(data["summary"]["dropped_below_floor"], 0)


class StorageScanWindowsPathTest(unittest.TestCase):
    """Windows 分支：只验路径拼接和前缀，不真跑扫描。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cfo-scan-win-")
        self.profile = os.path.join(self.tmp, "Users", "someone")
        os.makedirs(self.profile)
        self.original_platform = sys.platform
        self.original_drives = storage_scan._windows_drive_letters
        sys.platform = "win32"
        storage_scan._windows_drive_letters = lambda: []

    def tearDown(self):
        sys.platform = self.original_platform
        storage_scan._windows_drive_letters = self.original_drives
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scanner(self):
        return storage_scan.StorageScanner(home=self.profile, with_system=False)

    def test_platform_detected_from_sys_platform(self):
        scanner = self.scanner()
        self.assertTrue(scanner.is_windows)
        self.assertEqual(scanner.home_token, "%USERPROFILE%")
        self.assertEqual(scanner.sep, "\\")

    def test_group_target_paths(self):
        scanner = self.scanner()
        specs = dict(scanner.group_specs())
        expected = {
            "dev_caches", "downloads_installers", "recycle_bin",
            "appdata_local", "appdata_roaming", "projects_regenerable",
            "user_top",
        }
        self.assertEqual(expected, set(specs))

        self.assertEqual(specs["user_top"][1], self.profile)
        self.assertEqual(
            specs["appdata_local"][1][0],
            os.path.join(self.profile, "AppData", "Local"),
        )
        self.assertEqual(
            specs["appdata_roaming"][1],
            os.path.join(self.profile, "AppData", "Roaming"),
        )
        self.assertIn(os.path.join(self.profile, ".npm"), specs["dev_caches"])
        self.assertEqual(
            specs["downloads_installers"][1],
            os.path.join(self.profile, "Downloads"),
        )
        self.assertTrue(specs["recycle_bin"][0].endswith("$Recycle.Bin"))

        extras = specs["appdata_local"][1][1]
        local = os.path.join(self.profile, "AppData", "Local")
        self.assertIn(os.path.join(local, "Temp"), extras)
        self.assertIn(os.path.join(local, "pip", "Cache"), extras)
        self.assertIn(os.path.join(local, "npm-cache"), extras)
        self.assertIn(os.path.join(local, "Yarn"), extras)
        self.assertIn(os.path.join(local, "NuGet"), extras)
        self.assertIn(
            os.path.join(local, "Google", "Chrome", "User Data"), extras
        )

    def test_portable_prefix_uses_userprofile(self):
        scanner = self.scanner()
        local = os.path.join(self.profile, "AppData", "Local")
        self.assertEqual(
            scanner.portable(local), "%USERPROFILE%\\AppData\\Local"
        )
        self.assertEqual(scanner.portable(self.profile), "%USERPROFILE%")
        outside = os.path.join(self.tmp, "elsewhere")
        self.assertEqual(scanner.portable(outside), outside)

    def test_windows_system_notes(self):
        notes = self.scanner().system_notes()
        names = " ".join(note["name"] for note in notes)
        self.assertIn("WinSxS", names)
        self.assertIn("hiberfil.sys", names)
        self.assertIn("pagefile.sys", names)
        for note in notes:
            self.assertIsNone(note["size_bytes"])
            self.assertFalse(note["scanned"])

    def test_chrome_user_data_is_red(self):
        scanner = self.scanner()
        path = os.path.join(
            self.profile, "AppData", "Local", "Google", "Chrome", "User Data"
        )
        self.assertTrue(scanner.is_red(path))
        self.assertEqual(
            scanner.suggest_color(path, "app_data", "appdata_local"), "red"
        )

    def test_windows_disks_use_injected_drives(self):
        storage_scan._windows_drive_letters = lambda: []
        scanner = self.scanner()
        disks = scanner.collect_disks()
        self.assertIsInstance(disks, list)


class StorageScanCliTest(unittest.TestCase):
    """命令行入口：确认能落盘、能读回、只读。"""

    def test_cli_writes_json(self):
        tmp = tempfile.mkdtemp(prefix="cfo-scan-cli-")
        try:
            home = os.path.join(tmp, "home")
            os.makedirs(home)
            build_fake_home(home)
            out = os.path.join(tmp, "out", "storage-scan.json")
            before = sorted(os.listdir(home))
            proc = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "storage_scan.py"),
                 "--home", home, "--out", out, "--budget-seconds", "20",
                 "--min-size-mb", "0", "--quiet"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            with open(out, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["schema"], "storage-scan/1")
            self.assertTrue(data["groups"])
            self.assertLessEqual(data["elapsed_seconds"], 25)
            self.assertEqual(before, sorted(os.listdir(home)),
                             "扫描器动了假 home 里的东西")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
