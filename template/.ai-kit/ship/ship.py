#!/usr/bin/env python3
"""ship — 单机裸机发布工具（只用 Python 标准库，需要 3.11+ 的 tomllib）。

适用：一台服务器上的小项目，用 release 目录 + current 软链 + systemd 运行，
可选带一个需要在发布前快照、回滚时按库结构恢复的数据库。

    ship deploy [--init] [--skip-tests] [--allow-dirty]
                [--package P --expect-version V --expect-sha256 H --expect-previous V]
    ship rollback        回滚到上一个 release（只切代码；库结构不一致时提示恢复快照）
    ship unlock          释放残留的发布锁（确认没有发布在运行后再用）
    ship status          当前版本、release、快照、锁与最近的发布记录

配置：项目根的 deploy.toml（模板见 .ai-kit/ship/deploy.toml.example）。
个人覆盖：deploy.local.toml（不入库，常放主机名），再往上是环境变量 SHIP_*。
host = "local" 表示在服务器本机执行（补丁更新器用），此时不读个人覆盖、不做发布前预检。

流程：预检 → 构建 → 打包 → 上传 → 停服务并快照 → 切软链 → 重启 → 健康检查 →
失败自动回滚（库结构被改过则先恢复快照）→ 清理旧 release / 快照 → 可选公网检查。
退出码：0 成功；1 失败；3 已发布但公网检查失败（不回滚）。
"""
import argparse
import copy
import hashlib
import json
import os
import shlex
import socket
import subprocess
import sys
import tarfile
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None

q = shlex.quote
OK, FAIL, PUBLIC_FAIL = 0, 1, 3

DEFAULTS = {
    'config': {'local': 'deploy.local.toml'},   # 个人覆盖文件（相对项目根），不入库
    'server': {
        'host': '', 'dir': '/opt/app', 'service': 'app',
        'unit': '',               # systemd unit 文件（--init 时安装），如 deploy/app.service
        'env_default': '',        # --init 时 service.env 不存在则写入这一行，如 PUBLIC_ORIGIN=
        'legacy_marker': '',      # 存在此文件（相对 dir）视为旧的扁平安装，--init 时迁入 releases/legacy-*
        'keep_releases': 5, 'lock_ttl': 1800, 'settle': 2,
    },
    'build': {
        'test': [], 'build': [], 'artifacts': [],
        'package': '', 'package_path': 'dist/app.tar.gz', 'version_file': 'VERSION',
    },
    'health': {
        'url': '', 'version_field': 'version', 'ok_field': 'ok', 'retries': 5, 'interval': 3,
        'public_url': '', 'public_paths': [],
    },
    'data': {
        'kind': 'none',           # none | sqlite | command
        'path': '',               # 相对 server.dir，如 data/app.sqlite3
        'keep_snapshots': 5,
        'schema_query': '',       # sqlite：返回 schema 版本的 SQL，如 SELECT data FROM meta WHERE key='schema'
        'schema_json': True,      # schema_query 的结果是否为 JSON 编码
        'snapshot_cmd': '', 'restore_cmd': '', 'schema_cmd': '',   # command：占位符 {path} {snapshot} {dir}
    },
}
ENV_MAP = {
    'SHIP_HOST': ('server', 'host', str), 'SHIP_DIR': ('server', 'dir', str),
    'SHIP_SERVICE': ('server', 'service', str), 'SHIP_KEEP_RELEASES': ('server', 'keep_releases', int),
    'SHIP_LOCK_TTL': ('server', 'lock_ttl', int), 'SHIP_SETTLE': ('server', 'settle', int),
    'SHIP_KEEP_SNAPSHOTS': ('data', 'keep_snapshots', int),
    'SHIP_HEALTH_URL': ('health', 'url', str), 'SHIP_PUBLIC_URL': ('health', 'public_url', str),
}


class Abort(Exception):
    def __init__(self, message, code=FAIL):
        super().__init__(message)
        self.code = code


def say(message): print(f'\033[1;34m[ship]\033[0m {message}', flush=True)
def warn(message): print(f'\033[1;33m[ship]\033[0m {message}', file=sys.stderr, flush=True)
def die(message, code=FAIL): raise Abort(message, code)


# ── 配置 ───────────────────────────────────────────────────────────
def merge(base, extra):
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value


def read_toml(path):
    if tomllib is None:
        die('需要 Python 3.11+（tomllib）来读取 deploy.toml')
    with open(path, 'rb') as handle:
        return tomllib.load(handle)


def load_config(root, config_path=None):
    cfg = copy.deepcopy(DEFAULTS)
    path = Path(config_path or os.environ.get('SHIP_CONFIG') or root / 'deploy.toml')
    if not path.is_file():
        die(f'找不到配置文件 {path}（参考 .ai-kit/ship/deploy.toml.example）')
    merge(cfg, read_toml(path))
    host = os.environ.get('SHIP_HOST') or cfg['server']['host']
    if host != 'local':   # 个人覆盖只在开发机上读；补丁更新器（local）不读
        local = Path(os.environ.get('SHIP_LOCAL_CONFIG') or root / cfg['config']['local'])
        if local.is_file():
            merge(cfg, read_toml(local))
    for name, (section, key, cast) in ENV_MAP.items():
        if os.environ.get(name):
            cfg[section][key] = cast(os.environ[name])
    if not cfg['server']['host']:
        die('未指定主机：在 deploy.local.toml 写 [server] host = "<ssh主机>"，或设置 SHIP_HOST')
    if int(cfg['data']['keep_snapshots']) < 1:
        die('data.keep_snapshots 必须不小于 1')
    return cfg


# ── 目标机器（本机 bash 或 ssh）────────────────────────────────────
class Target:
    def __init__(self, host):
        self.host = host
        self.local = host == 'local'
        self.ssh = ['ssh', '-o', 'ControlMaster=auto', '-o', 'ControlPersist=120',
                    '-o', 'ControlPath=/tmp/ship-cm-%C']

    def run(self, command, input=None, quiet=False):
        """执行命令，返回 (退出码, 标准输出)；标准错误直接透传，quiet 时丢弃。"""
        argv = ['bash', '-c', command] if self.local else [*self.ssh, self.host, command]
        done = subprocess.run(argv, input=input, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL if quiet else None,
                              stdin=None if input is not None else subprocess.DEVNULL)
        return done.returncode, done.stdout.strip()

    def ok(self, command, **kwargs):
        return self.run(command, **kwargs)[0] == 0

    def out(self, command, **kwargs):
        code, text = self.run(command, **kwargs)
        return text if code == 0 else ''

    def put(self, source, destination):
        if self.local:
            subprocess.run(['cp', source, destination], check=True)
        else:
            subprocess.run(['scp', '-q', '-o', 'ControlMaster=auto', '-o', 'ControlPath=/tmp/ship-cm-%C',
                            source, f'{self.host}:{destination}'], check=True)

    def close(self):
        if not self.local:
            subprocess.run([*self.ssh, '-O', 'exit', self.host], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)


def pause(seconds):
    if seconds > 0:
        subprocess.run(['sleep', str(seconds)])   # 走 PATH 里的 sleep，测试可替换


# ── 发布上下文 ─────────────────────────────────────────────────────
class Ship:
    def __init__(self, root, cfg):
        self.root, self.cfg = Path(root), cfg
        self.t = Target(cfg['server']['host'])
        self.base = cfg['server']['dir'].rstrip('/')
        self.service = cfg['server']['service']
        self.lock = f'{self.base}/.deploy-lock'
        self.stamp = time.strftime('%Y%m%d-%H%M%S')
        data = cfg['data']
        self.data_path = f"{self.base}/{data['path']}" if data['path'] else ''
        ext = os.path.splitext(data['path'])[1]
        self.snap_ext = ext
        self.snap = f"{os.path.dirname(self.data_path)}/pre-deploy-{self.stamp}{ext}" if self.data_path else ''
        self.snap_schema = ''
        self.locked = False

    # 服务器上的小工具
    def sudo(self, command, **kwargs): return self.t.run(f'sudo -n {command}', **kwargs)
    def restart(self): return self.t.run(f'sudo systemctl restart {q(self.service)}')[0] == 0
    def switch_to(self, release): return self.t.ok(f"ln -sfn {q(release)} {q(self.base + '/current')}")

    def log(self, text):
        who = f"{os.environ.get('USER', '?')}@{socket.gethostname().split('.')[0]}"
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {text} by={who}"
        self.t.run(f"printf '%s\\n' {q(line)} | sudo -n tee -a {q(self.base + '/deploy.log')} >/dev/null")

    # ── 锁 ──
    def acquire(self):
        t = self.t
        if not t.ok(f"sudo -n mkdir -p {q(self.base)} && sudo -n mkdir {q(self.lock)}", quiet=True):
            if t.ok(f'[ -d {q(self.lock)} ]', quiet=True):
                self.describe_lock()
            die(f'发布目录不可写：{self.base}')
        self.locked = True
        who = f"{os.environ.get('USER', '?')}@{socket.gethostname().split('.')[0]}"
        t.run(f"printf '%s\\n' {q(f'{int(time.time())} {who}')} | sudo -n tee {q(self.lock + '/info')} >/dev/null")

    def describe_lock(self):
        info = self.t.out(f"cat {q(self.lock + '/info')} 2>/dev/null")
        now = self.t.out("date +%s", quiet=True)
        started, _, who = info.partition(' ')
        if not (started.isdigit() and now.isdigit()):
            die('已有发布正在执行（无法读取锁信息）；确认没有发布在运行后可用 ship unlock 释放')
        age = int(now) - int(started)
        ttl = int(self.cfg['server']['lock_ttl'])
        if age > ttl:
            die(f'已有发布正在执行（{who}，{age // 60} 分钟前开始，已超过 {ttl // 60} 分钟）；'
                '若确认没有发布在运行，用 --unlock 释放')
        die(f'已有发布正在执行（{who}，{age // 60} 分钟前开始）；稍后重试')

    def release_lock(self):
        if self.locked:
            self.t.run(f"sudo -n rm -rf {q(self.lock)}")
            self.locked = False

    # ── 健康检查 ──
    def health(self):
        url = self.cfg['health']['url']
        if not url:
            die('未配置 health.url')
        code, out = self.t.run(f'curl -fsS -m 10 {q(url)}', quiet=True)
        return out if code == 0 else None

    def healthy(self, body, expected):
        h = self.cfg['health']
        try:
            doc = json.loads(body)
        except (TypeError, ValueError):
            return False
        if h['ok_field'] and doc.get(h['ok_field']) is not True:
            return False
        return doc.get(h['version_field']) == expected

    # ── 数据库快照 ──
    def has_data(self): return self.cfg['data']['kind'] != 'none' and bool(self.data_path)

    def schema_of(self, file):
        data = self.cfg['data']
        if data['kind'] == 'sqlite' and data['schema_query']:
            script = ("import json, sqlite3, sys\n"
                      "try:\n"
                      "    row = sqlite3.connect('file:%s?mode=ro' % sys.argv[1], uri=True).execute(sys.argv[2]).fetchone()\n"
                      "    print((json.loads(row[0]) if sys.argv[3] == '1' else row[0]) if row else '')\n"
                      "except Exception:\n"
                      "    print('')\n")
            flag = '1' if data['schema_json'] else '0'
            return self.t.out(f'sudo -n python3 - {q(file)} {q(data["schema_query"])} {flag}', input=script, quiet=True)
        if data['kind'] == 'command' and data['schema_cmd']:
            return self.t.out(data['schema_cmd'].format(path=file, dir=self.base), quiet=True)
        return ''

    def take_snapshot(self):
        data = self.cfg['data']
        if data['kind'] == 'sqlite':
            return self.t.ok(f"sudo -n sh -c 'if [ -f {q(self.data_path)} ]; then cp {q(self.data_path)} {q(self.snap)}; fi'")
        return self.t.ok(f"sudo -n sh -c {q(data['snapshot_cmd'].format(path=self.data_path, snapshot=self.snap, dir=self.base))}")

    def restore_snapshot(self):
        data = self.cfg['data']
        if data['kind'] == 'sqlite':
            return self.t.ok(f'sudo -n cp {q(self.snap)} {q(self.data_path)}')
        return self.t.ok(f"sudo -n sh -c {q(data['restore_cmd'].format(path=self.data_path, snapshot=self.snap, dir=self.base))}")

    def prune_snapshots(self):
        keep = int(self.cfg['data']['keep_snapshots'])
        folder = os.path.dirname(self.data_path)
        self.t.run(f"sudo -n sh -c 'cd {q(folder)} 2>/dev/null && ls -1 pre-deploy-[0-9]*-[0-9]*{self.snap_ext} "
                   f"2>/dev/null | sort | head -n -{keep} | xargs -r rm -f --'")

    # ── 回滚 ──
    def rollback_and_die(self, previous, expected):
        restored = 'no'
        say(f'健康检查失败，回滚到 {previous}')
        self.switch_to(previous)
        if self.has_data() and self.snap_schema:
            now = self.schema_of(self.data_path)
            if now and now != self.snap_schema:
                say(f'库结构 {self.snap_schema} → {now} 已被新版本改动，恢复发布前快照 {os.path.basename(self.snap)}')
                self.t.run(f'sudo -n systemctl stop {q(self.service)}')
                if self.restore_snapshot():
                    restored = 'yes'
                else:
                    warn(f'快照恢复失败，请手动处理：{self.snap}')
        self.restart()
        pause(self.cfg['server']['settle'])
        self.log(f'ROLLBACK from={expected or "?"} to={os.path.basename(previous)} db_restored={restored}')
        die(f'已回滚到 {previous}（库快照恢复：{restored}）；请查看远端 journalctl -u {self.service} -n 50 定位问题')


# ── 发布前预检与构建（本机）────────────────────────────────────────
def shell(command, cwd):
    done = subprocess.run(command, shell=True, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return done.returncode, done.stdout


def git(root, *args):
    done = subprocess.run(['git', *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return done.returncode, done.stdout.strip()


def preflight(ship, args):
    root = ship.root
    code, dirty = git(root, 'status', '--porcelain', '--untracked-files=no')
    if dirty and not args.allow_dirty:
        print(dirty, file=sys.stderr)
        die('工作树有未提交的改动：版本号会带 -dirty，线上代码与仓库对不上。先提交，或加 --allow-dirty')
    code, upstream = git(root, 'rev-parse', '--abbrev-ref', '@{u}')
    if code == 0:
        _, ahead = git(root, 'rev-list', '--count', '@{u}..HEAD')
        if ahead not in ('', '0'):
            warn(f'有 {ahead} 个提交尚未推送到远程；线上版本会领先于仓库')
    else:
        warn('当前分支没有上游，无法确认是否已推送')
    if args.skip_tests:
        warn('已跳过发布前测试（--skip-tests）')
        return
    for command in ship.cfg['build']['test']:
        say(f'测试：{command}')
        code, output = shell(command, root)
        if code:
            print('\n'.join(output.splitlines()[-40:]), file=sys.stderr)
            die(f'测试未通过：{command}，已中止（--skip-tests 可跳过）')


def build_package(ship, args):
    b = ship.cfg['build']
    preflight(ship, args)
    for command in b['build']:
        say(f'构建：{command}')
        code, output = shell(command, ship.root)
        if code:
            print('\n'.join(output.splitlines()[-40:]), file=sys.stderr)
            die(f'构建失败：{command}')
    if b['artifacts'] and not args.allow_dirty:
        _, changed = git(ship.root, 'status', '--porcelain', '--', *b['artifacts'])
        if changed:
            print(changed, file=sys.stderr)
            die('构建产物与已提交的内容不一致：先把重新构建的产物提交，或加 --allow-dirty')
    if not b['package']:
        die('未配置 build.package（打包命令）')
    say('打包…')
    code, output = shell(b['package'], ship.root)
    print(output, end='')
    if code:
        die('打包失败')
    return str((ship.root / b['package_path']).resolve())


def package_version(path, version_file):
    with tarfile.open(path) as archive:
        member = archive.extractfile(version_file)
        if member is None:
            die(f'发布包里没有 {version_file}')
        return member.read().decode().strip()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ── 子命令 ─────────────────────────────────────────────────────────
def init_layout(ship, stamp):
    t, base, srv = ship.t, ship.base, ship.cfg['server']
    marker = srv['legacy_marker']
    if marker and t.ok(f"[ -f {q(base + '/' + marker)} ]"):
        say(f'检测到扁平安装，迁入 releases/legacy-{stamp}（data/ 原地保留）')
        t.run(f"mkdir -p {q(base + '/releases/legacy-' + stamp)} && cd {q(base)} && find . -maxdepth 1 -mindepth 1 "
              f"! -name data ! -name releases ! -name service.env ! -name current ! -name .deploy-lock "
              f"-exec mv {{}} releases/legacy-{stamp}/ \\;")
    if srv['unit']:
        unit = ship.root / srv['unit']
        say(f"安装 systemd unit（{ship.service}，按需先在服务器创建运行用户）")
        t.put(str(unit), f'/tmp/{ship.service}.service')
        t.run(f"sudo mv /tmp/{q(ship.service)}.service /etc/systemd/system/{q(ship.service)}.service && "
              f"sudo systemctl daemon-reload && sudo systemctl enable {q(ship.service)}")
    if srv['env_default']:
        t.run(f"[ -f {q(base + '/service.env')} ] || {{ echo {q(srv['env_default'])} > {q(base + '/service.env')}; "
              f"chmod 600 {q(base + '/service.env')}; }}")


def cmd_deploy(ship, args):
    t, base, cfg = ship.t, ship.base, ship.cfg
    if args.expect_previous:
        current = t.out(f"cat {q(base + '/current/VERSION')}")
        if current == args.expect_version:
            return OK
        if current != args.expect_previous:
            die('运行版本已变更，请重新检查更新')
    package = args.package or ''
    if not package:
        package = build_package(ship, args)
    package = str(Path(package).resolve())
    version = package_version(package, cfg['build']['version_file'])
    expected = args.expect_version or version
    if version != expected:
        die('发布包版本与目标版本不一致')
    if args.expect_sha256 and sha256(package) != args.expect_sha256:
        die('发布包 SHA256 校验失败')

    stamp = ship.stamp
    release = f'{base}/releases/{stamp}'
    t.run(f"mkdir -p {q(base + '/releases')}")
    say(f'上传并解压到 releases/{stamp} …')
    remote_tmp = f'/tmp/ship-{ship.service}-{stamp}.tar.gz'
    t.put(package, remote_tmp)
    t.run(f"mkdir -p {q(release)} && tar -xzf {q(remote_tmp)} -C {q(release)} && rm {q(remote_tmp)}")
    # 补丁更新器以 root 运行且 UMask 收紧，解压出的 release 会是 root 私有目录，应用用户进不去；
    # 对齐当前版本的属主并放开读取
    t.run(f"chmod -R u+rwX,go+rX {q(release)}")
    t.run(f"chown -R --reference={q(base + '/current')} {q(release)} 2>/dev/null || true")
    if args.init:
        init_layout(ship, stamp)

    previous = t.out(f"readlink {q(base + '/current')} || true")
    previous_version = t.out(f"cat {q(base + '/current/VERSION')} 2>/dev/null")
    say('停服务并快照数据库' if ship.has_data() else '停服务')
    t.run(f'sudo -n systemctl stop {q(ship.service)}')
    if ship.has_data():
        # 快照要在 root 下执行：数据目录通常 0700，以 ssh 登录用户判断「是否存在」会误判而静默跳过
        if not ship.take_snapshot():
            ship.restart()
            die('发布前快照失败，保留原版本')
        if t.ok(f'sudo -n test -f {q(ship.snap)}', quiet=True):
            ship.snap_schema = ship.schema_of(ship.snap)

    if not ship.switch_to(release) or not ship.restart():
        if previous:
            ship.rollback_and_die(previous, expected)
        die('新版本启动失败且没有可回滚的旧版本')

    h = cfg['health']
    pause(cfg['server']['settle'])
    for attempt in range(1, int(h['retries']) + 1):
        body = ship.health()
        if body is not None and ship.healthy(body, expected):
            say(f'健康检查通过：{body}')
            new_schema = ship.schema_of(ship.data_path) if ship.has_data() else ''
            say(f'发布完成：{release}（上一版：{previous or "无"}）')
            if ship.snap_schema and new_schema and ship.snap_schema != new_schema:
                warn(f'数据库结构 {ship.snap_schema} → {new_schema} 已升级：之后手动回滚到旧版前须先恢复快照 {os.path.basename(ship.snap)}')
            snapshot = os.path.basename(ship.snap) if ship.has_data() else '-'
            ship.log(f'OK {expected} prev={previous_version or "?"} schema={ship.snap_schema or "?"}->{new_schema or "?"} snapshot={snapshot}')
            keep = int(cfg['server']['keep_releases'])
            # 只清理命名规范的过期 release；运行服务会创建其他属主的 __pycache__，必须 sudo 删除
            t.run(f"cd {q(base + '/releases')} && ls -1d [0-9]*-[0-9]*/ | grep -E '^[0-9]{{8}}-[0-9]{{6}}/$' | sort | head -n -{keep} | xargs -r sudo -n rm -rf --")
            if ship.has_data():
                ship.prune_snapshots()
            return public_check(ship, expected)
        say(f'等待服务就绪（{attempt}/{h["retries"]}）…')
        pause(h['interval'])
    if previous:
        ship.rollback_and_die(previous, expected)
    die(f'健康检查失败且没有可回滚的旧版本；查看 journalctl -u {ship.service} -n 50')


def public_check(ship, expected):
    h = ship.cfg['health']
    url = h['public_url'].rstrip('/')
    if not url:
        return OK
    health_path = '/' + h['url'].split('://', 1)[-1].partition('/')[2]
    paths = [health_path, *h['public_paths']]
    for index, path in enumerate(paths):
        done = subprocess.run(['curl', '-fsS', '-m', '15', url + path], text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        good = done.returncode == 0
        if good and index == 0:
            good = ship.healthy(done.stdout, expected) if h['ok_field'] or h['version_field'] else True
        if not good:
            warn(f'公网检查失败：{url}{path}（本机健康检查已通过，未回滚）。请检查反向代理 / 证书 / DNS。')
            return PUBLIC_FAIL
    say(f'公网检查通过：{url}')
    return OK


def cmd_rollback(ship, args):
    t, base = ship.t, ship.base
    current = t.out(f"readlink {q(base + '/current')} || true")
    if not current:
        die('没有 current 软链，无法回滚')
    listing = [line.rstrip('/') for line in
               t.out(f"ls -1d {q(base + '/releases')}/*/ | grep -v legacy | sort -r").splitlines()]
    # 取「当前版本的前一个」：连续回滚两次会继续往前走，而不是在最新两版之间来回切
    names = [os.path.basename(line) for line in listing]
    index = names.index(os.path.basename(current)) if os.path.basename(current) in names else 0
    if index + 1 >= len(listing):
        die('没有可回滚的旧版本')
    target = listing[index + 1]
    ship.switch_to(target)
    ship.restart()
    pause(ship.cfg['server']['settle'])
    if ship.health() is None:
        die('回滚后健康检查仍失败')
    say(f'已回滚到 {target}')
    ship.log(f'ROLLBACK-MANUAL to={os.path.basename(target)}')
    if ship.has_data():
        folder = os.path.dirname(ship.data_path)
        latest = t.out(f"sudo -n sh -c 'ls -1 {q(folder)}/pre-deploy-[0-9]*-[0-9]*{ship.snap_ext} 2>/dev/null | sort | tail -n 1'")
        if latest:
            old, live = ship.schema_of(latest), ship.schema_of(ship.data_path)
            if old and live and old != live:
                warn(f'数据库结构是 {live}，最近快照是 {old}：旧代码可能读不了现在的库。')
                warn(f'确认后再恢复（会丢失快照之后的写入）：停服务 → 复制 {latest} 覆盖 {ship.data_path} → 启服务。')
    return OK


def cmd_status(ship, args):
    t, base = ship.t, ship.base
    current = t.out(f"readlink {q(base + '/current')}") or '无'
    version = t.out(f"cat {q(base + '/current/VERSION')}") or '?'
    say(f'当前：{current}（{version}）')
    body = ship.health()
    say(f'健康检查：{body if body is not None else "不可达"}')
    print('releases：')
    print(t.out(f"ls -1 {q(base + '/releases')} 2>/dev/null | tail -n 8") or '  （无）')
    if ship.has_data():
        folder = os.path.dirname(ship.data_path)
        count = t.out(f"sudo -n sh -c 'ls -1 {q(folder)}/pre-deploy-*{ship.snap_ext} 2>/dev/null | wc -l'")
        say(f'发布前快照：{count.strip() or 0} 份（保留 {ship.cfg["data"]["keep_snapshots"]}）')
    info = t.out(f"cat {q(ship.lock + '/info')} 2>/dev/null")
    say(f'发布锁：{info or "未占用"}')
    tail = t.out(f"tail -n 5 {q(base + '/deploy.log')} 2>/dev/null")
    if tail:
        print('最近发布记录：')
        print(tail)
    return OK


# ── 入口 ───────────────────────────────────────────────────────────
def build_parser():
    parser = argparse.ArgumentParser(prog='ship', description='单机裸机发布工具')
    parser.add_argument('--config', help='deploy.toml 路径（默认 项目根/deploy.toml）')
    parser.add_argument('--root', help='项目根目录（默认当前目录）')
    sub = parser.add_subparsers(dest='command')
    deploy = sub.add_parser('deploy', help='发布（默认）')
    deploy.add_argument('--init', action='store_true', help='首次发布：初始化 release 布局并安装 systemd unit')
    deploy.add_argument('--skip-tests', action='store_true')
    deploy.add_argument('--allow-dirty', action='store_true')
    deploy.add_argument('--package', help='使用已有发布包（不构建、不预检）')
    deploy.add_argument('--expect-version')
    deploy.add_argument('--expect-sha256')
    deploy.add_argument('--expect-previous')
    for name, text in (('rollback', '回滚上一版'), ('unlock', '释放发布锁'), ('status', '查看状态')):
        sub.add_parser(name, help=text)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {'deploy', 'rollback', 'unlock', 'status', '-h', '--help'}
    # 裸 ship（或只带全局选项）等同 ship deploy；全局选项在子命令之前
    leading = []
    rest = list(argv)
    while rest and rest[0] in ('--config', '--root') and len(rest) > 1:
        leading += rest[:2]
        rest = rest[2:]
    if not rest or rest[0] not in commands:
        rest = ['deploy', *rest]
    args = build_parser().parse_args([*leading, *rest])
    root = Path(args.root or os.getcwd()).resolve()
    ship = None
    try:
        cfg = load_config(root, args.config)
        ship = Ship(root, cfg)
        if args.command == 'unlock':
            ship.t.run(f'sudo -n rm -rf {q(ship.lock)}')
            say(f'已释放发布锁 {ship.lock}')
            return OK
        if args.command == 'status':
            return cmd_status(ship, args)
        ship.acquire()
        try:
            return cmd_rollback(ship, args) if args.command == 'rollback' else cmd_deploy(ship, args)
        finally:
            ship.release_lock()
    except Abort as exc:
        print(f'\033[1;31m[ship]\033[0m {exc}', file=sys.stderr)
        return exc.code
    finally:
        if ship is not None:
            ship.t.close()


if __name__ == '__main__':
    sys.exit(main())
