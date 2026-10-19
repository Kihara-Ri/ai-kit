"""ship 的黑盒测试：host = "local"，用 PATH 里的替身（sudo / systemctl / curl / cp / head / sleep）
模拟服务器，不碰真实系统。运行：python3 -m unittest discover -s tests"""
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

SHIP = Path(__file__).resolve().parents[1] / 'template' / '.ai-kit' / 'ship' / 'ship.py'

TOML = '''
[server]
host = "local"
dir = "{base}"
service = "fixture"
keep_releases = 5
settle = 0

[health]
url = "http://127.0.0.1:9/api/health"
interval = 0
public_url = ""

[data]
kind = "sqlite"
path = "data/app.sqlite3"
schema_query = "SELECT data FROM meta WHERE key='schema'"
keep_snapshots = 5
'''


def make_package(path, version):
    with tarfile.open(path, 'w:gz') as archive:
        for name, body in (('VERSION', version.encode()), ('app.py', b'# fixture\n')):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))


STUBS = {
    'sudo': '#!/bin/sh\n[ "$1" != -n ] || shift\nexec "$@"\n',
    # migrate：新版本一启动就把库结构升到 5（模拟一次性 schema 升级）
    'systemctl': '''#!/bin/sh
printf "%s\\n" "$*" >> "$FIXTURE_LOG"
if [ "$FIXTURE_FAILURE" = migrate ] && [ "$1" = restart ] && grep -q v2 "$SHIP_DIR/current/VERSION"; then
  python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(\\"INSERT OR REPLACE INTO meta VALUES('schema','5')\\"); c.commit()" "$SHIP_DIR/data/app.sqlite3"
fi
''',
    'sleep': '#!/bin/sh\nexit 0\n',
    'curl': '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = ' '.join(sys.argv)
v = (pathlib.Path(os.environ['SHIP_DIR']) / 'current' / 'VERSION').read_text().strip()
failure = os.environ.get('FIXTURE_FAILURE')
if failure in ('health', 'migrate') and v == 'v2' and 'example.test' not in args:
    v = 'wrong-version'
if failure == 'public' and 'example.test' in args:
    sys.exit(22)
print(json.dumps({'ok': True, 'version': v}))
''',
    'cp': '''#!/bin/sh
if [ "$FIXTURE_FAILURE" = backup ]; then
  case "$2" in *pre-deploy-*) exit 1;; esac
fi
exec /bin/cp "$@"
''',
    # 服务器上的 GNU head -n -N
    'head': '''#!/usr/bin/env python3
import sys
lines = sys.stdin.readlines(); n = int(sys.argv[-1]); sys.stdout.writelines(lines[:n])
''',
}


class ShipCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.base = tmp / 'instance'
        old = self.base / 'releases' / 'old'
        old.mkdir(parents=True)
        (old / 'VERSION').write_text('v1')
        (self.base / 'current').symlink_to(old)
        self.db = self.base / 'data' / 'app.sqlite3'
        self.db.parent.mkdir()
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE meta(key TEXT PRIMARY KEY, data TEXT)')
        con.execute("INSERT INTO meta VALUES('schema','4')")
        con.commit(); con.close()
        self.original = self.db.read_bytes()
        self.root = tmp / 'project'
        self.root.mkdir()
        (self.root / 'deploy.toml').write_text(TOML.format(base=self.base))
        self.package = tmp / 'app.tar.gz'
        make_package(self.package, 'v2')
        bindir = tmp / 'bin'
        bindir.mkdir()
        for name, body in STUBS.items():
            (bindir / name).write_text(body)
            (bindir / name).chmod(0o755)
        self.log = tmp / 'service.log'
        self.env = {**os.environ, 'PATH': f'{bindir}{os.pathsep}{os.environ["PATH"]}',
                    'SHIP_DIR': str(self.base), 'FIXTURE_LOG': str(self.log), 'FIXTURE_FAILURE': ''}
        for key in [k for k in self.env if k.startswith('SHIP_') and k != 'SHIP_DIR']:
            del self.env[key]

    def tearDown(self):
        self.tmp.cleanup()

    def ship(self, *args, failure='', cwd=None, env=None):
        run_env = {**self.env, 'FIXTURE_FAILURE': failure, **(env or {})}
        done = subprocess.run([sys.executable, str(SHIP), '--root', str(cwd or self.root), *args],
                              env=run_env, capture_output=True, text=True, timeout=60, cwd=cwd or self.root)
        done.text = done.stdout + done.stderr
        return done

    def deploy(self, *extra, **kwargs):
        return self.ship('deploy', '--package', str(self.package), '--expect-version', 'v2', *extra, **kwargs)

    def assert_preserved(self, version):
        self.assertEqual((self.base / 'current' / 'VERSION').read_text(), version)
        self.assertEqual(self.db.read_bytes(), self.original)
        self.assertFalse((self.base / '.deploy-lock').exists())


class DeployFlow(ShipCase):
    def test_success_snapshots_switches_logs_and_prunes(self):
        data = self.base / 'data'
        for i in range(1, 8):
            (data / f'pre-deploy-20260101-0000{i:02d}.sqlite3').write_bytes(b'old')
        result = self.deploy(env={'SHIP_KEEP_SNAPSHOTS': '3'})
        self.assertEqual(result.returncode, 0, result.text)
        names = sorted(p.name for p in data.glob('pre-deploy-*.sqlite3'))
        self.assertEqual(len(names), 3, names)
        self.assertTrue(names[2].startswith('pre-deploy-2'))
        self.assert_preserved('v2')
        self.assertIn(' OK v2 prev=v1 schema=4->4 snapshot=pre-deploy-', (self.base / 'deploy.log').read_text())

    def test_wrong_health_version_rolls_back(self):
        result = self.deploy(failure='health')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('已回滚', result.text)
        self.assert_preserved('v1')

    def test_snapshot_failure_restarts_previous_service_without_switching(self):
        result = self.deploy(failure='backup')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('快照失败', result.text)
        self.assert_preserved('v1')
        self.assertIn('restart fixture', self.log.read_text())

    def test_schema_upgrade_failure_restores_database_snapshot(self):
        result = self.deploy(failure='migrate')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('恢复发布前快照', result.text)
        self.assert_preserved('v1')   # 库字节与发布前完全一致
        self.assertIn('ROLLBACK from=v2', (self.base / 'deploy.log').read_text())

    def test_expect_previous_mismatch_aborts_without_touching_service(self):
        result = self.deploy('--expect-previous', 'v0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('运行版本已变更', result.text)
        self.assert_preserved('v1')
        self.assertFalse(self.log.exists())

    def test_already_current_version_is_a_noop(self):
        (self.base / 'current' / 'VERSION').write_text('v2')
        result = self.deploy('--expect-previous', 'v1')
        self.assertEqual(result.returncode, 0, result.text)
        self.assertFalse(self.log.exists())

    def test_wrong_sha256_is_rejected(self):
        result = self.deploy('--expect-sha256', '0' * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA256', result.text)
        self.assertEqual((self.base / 'current' / 'VERSION').read_text(), 'v1')

    def test_correct_sha256_is_accepted(self):
        digest = hashlib.sha256(self.package.read_bytes()).hexdigest()
        self.assertEqual(self.deploy('--expect-sha256', digest).returncode, 0)

    def test_project_without_database_deploys_without_snapshots(self):
        (self.root / 'deploy.toml').write_text(TOML.format(base=self.base).replace('kind = "sqlite"', 'kind = "none"'))
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.text)
        self.assertEqual(list((self.base / 'data').glob('pre-deploy-*')), [])
        self.assertEqual((self.base / 'current' / 'VERSION').read_text(), 'v2')


class LockAndRollback(ShipCase):
    def test_held_lock_reports_owner_and_stale_hint_without_stealing_it(self):
        lock = self.base / '.deploy-lock'
        lock.mkdir()
        (lock / 'info').write_text(f'{int(time.time()) - 60} tester@host\n')
        result = self.deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('tester@host', result.text)
        self.assertNotIn('--unlock', result.text)
        (lock / 'info').write_text(f'{int(time.time()) - 7200} tester@host\n')
        self.assertIn('unlock', self.deploy().text)
        self.assertTrue(lock.exists())   # 他人的锁不能被失败的发布顺手删掉
        self.assertEqual(self.ship('unlock').returncode, 0)
        self.assertFalse(lock.exists())

    def test_manual_rollback_switches_code_and_warns_when_schema_differs(self):
        (self.base / 'releases' / '20260101-000001').mkdir()
        (self.base / 'releases' / '20260101-000001' / 'VERSION').write_text('v0')
        (self.base / 'releases' / '20260102-000001').mkdir()
        (self.base / 'releases' / '20260102-000001' / 'VERSION').write_text('v1')
        (self.base / 'current').unlink()
        (self.base / 'current').symlink_to(self.base / 'releases' / '20260102-000001')
        snap = self.base / 'data' / 'pre-deploy-20260102-000001.sqlite3'
        snap.write_bytes(self.original)
        sqlite3.connect(self.db).execute("INSERT OR REPLACE INTO meta VALUES('schema','9')").connection.commit()
        result = self.ship('rollback')
        self.assertEqual(result.returncode, 0, result.text)
        self.assertEqual((self.base / 'current' / 'VERSION').read_text(), 'v0')
        self.assertIn('旧代码可能读不了现在的库', result.text)
        self.assertIn('ROLLBACK-MANUAL', (self.base / 'deploy.log').read_text())

    def test_status_reports_current_version_and_health(self):
        result = self.ship('status')
        self.assertEqual(result.returncode, 0, result.text)
        self.assertIn('v1', result.text)


class PublicCheck(ShipCase):
    def test_public_failure_exits_3_without_rollback_then_passes(self):
        (self.root / 'deploy.toml').write_text(TOML.format(base=self.base).replace(
            'public_url = ""', 'public_url = "https://example.test"\npublic_paths = ["/sw.js"]'))
        result = self.deploy(failure='public')
        self.assertEqual(result.returncode, 3, result.text)
        self.assertIn('公网检查失败', result.text)
        self.assertEqual((self.base / 'current' / 'VERSION').read_text(), 'v2')
        self.assertIn('公网检查通过', self.deploy().text)


class ConfigAndPreflight(ShipCase):
    def test_host_comes_from_local_override_and_env_wins(self):
        (self.root / 'deploy.toml').write_text(TOML.format(base=self.base).replace('host = "local"\n', ''))
        (self.root / 'deploy.local.toml').write_text('[server]\nhost = "local"\n\n[data]\nkeep_snapshots = 2\n')
        data = self.base / 'data'
        for i in (1, 2):
            (data / f'pre-deploy-20260101-00000{i}.sqlite3').write_bytes(b'old')
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.text)
        self.assertEqual(len(list(data.glob('pre-deploy-*.sqlite3'))), 2)
        # 环境变量优先于个人覆盖（发布时间戳精确到秒，等一秒避免两次发布共用同一份快照名）
        time.sleep(1.1)
        (data / 'pre-deploy-20260101-000003.sqlite3').write_bytes(b'old')
        self.deploy(env={'SHIP_KEEP_SNAPSHOTS': '4'})
        self.assertEqual(len(list(data.glob('pre-deploy-*.sqlite3'))), 4)

    def test_missing_host_is_explained(self):
        (self.root / 'deploy.toml').write_text(TOML.format(base=self.base).replace('host = "local"\n', ''))
        result = self.deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未指定主机', result.text)

    def test_local_host_ignores_personal_override(self):
        (self.root / 'deploy.local.toml').write_text('[server]\nhost = "definitely-not-reachable"\n')
        self.assertEqual(self.deploy().returncode, 0)

    def git_project(self, extra=''):
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
        run = lambda *a: subprocess.run(['git', *a], cwd=self.root, check=True, capture_output=True, env=env)
        (self.root / 'deploy.toml').write_text(TOML.format(base=self.base) + extra)
        (self.root / 'static').mkdir(exist_ok=True)
        (self.root / 'static' / 'a.txt').write_text('a')
        (self.root / 'tracked.txt').write_text('a')
        run('init', '-q'); run('add', '.'); run('commit', '-qm', 'init')
        return run

    def test_dirty_tree_aborts_before_building(self):
        self.git_project()
        (self.root / 'tracked.txt').write_text('changed')
        result = self.ship('deploy')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未提交的改动', result.text)
        self.assertFalse((self.base / '.deploy-lock').exists())
        self.assertEqual((self.base / 'current' / 'VERSION').read_text(), 'v1')

    def test_failing_test_command_aborts_and_skip_tests_bypasses_it(self):
        self.git_project('\n[build]\ntest = ["exit 1"]\nbuild = []\npackage = "false"\n')
        result = self.ship('deploy')
        self.assertIn('测试未通过', result.text)
        skipped = self.ship('deploy', '--skip-tests')
        self.assertIn('已跳过发布前测试', skipped.text)
        self.assertIn('打包失败', skipped.text)   # 越过测试关卡，走到了打包

    def test_artifacts_must_match_committed_files(self):
        self.git_project('\n[build]\nbuild = ["echo changed > static/a.txt"]\nartifacts = ["static"]\npackage = "false"\n')
        result = self.ship('deploy', '--skip-tests')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('构建产物与已提交的内容不一致', result.text)


if __name__ == '__main__':
    unittest.main()
