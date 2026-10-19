#!/usr/bin/env python3
"""Isolated publisher regressions. Python stdlib, git and bash; never use the network."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PUSH = ROOT / "skills/ljg-push/Tools/Push.sh"
SYNC = ROOT / "scripts/sync-push.sh"
ORIGIN = "https://github.com/johnson020202/ljg-skills260812.git"
REAL_GIT = shutil.which("git")

# A deny-by-default wrapper: even a broken publisher cannot invoke a Git transport.
# Its cwd and -C targets must stay inside this test's temporary directory.
GIT_STUB = r'''import json, os, pathlib, shutil, subprocess, sys
args = sys.argv[1:]
root = pathlib.Path(os.environ['TEST_ROOT']).resolve()
cwd = pathlib.Path.cwd().resolve()
i = 0
while i < len(args) and args[i].startswith('-'):
    if args[i] == '-C':
        cwd = (cwd / args[i+1]).resolve(); i += 2
    elif args[i] == '-c': i += 2
    elif args[i] in ('--no-optional-locks', '--literal-pathspecs'): i += 1
    else: sys.exit('Blocked Git option: ' + args[i])
if cwd != root and root not in cwd.parents: sys.exit('Git outside test root')
cmd = args[i] if i < len(args) else ''
rest = args[i+1:]
stdin = None
call = {'cmd':cmd, 'args':rest, 'cwd':str(cwd)}
if cmd == 'add':
    if '--pathspec-from-file=-' in rest:
        if '--pathspec-file-nul' not in rest: sys.exit('Expected NUL-delimited pathspecs')
        stdin = sys.stdin.buffer.read()
        if not stdin.endswith(b'\0'): sys.exit('Missing final NUL in pathspecs')
        call['paths'] = stdin[:-1].decode('utf-8').split('\0')
    else:
        call['paths'] = rest[rest.index('--')+1:] if '--' in rest else []
with open(os.environ['TEST_TRACE'], 'a') as f:
    f.write(json.dumps(call)+'\n')
if cmd in ('push', 'pull', 'fetch', 'clone', 'ls-remote'):
    if cmd == 'ls-remote':
        refs = json.loads(os.environ.get('TEST_REMOTE_REFS', '{}'))
        print(''.join(oid+'\trefs/heads/'+name+'\n' for name,oid in refs.items()), end='')
    elif cmd == 'push':
        commits = {}
        for ref in rest:
            if ':refs/heads/' in ref and not ref.startswith('-'):
                source, target = ref.split(':', 1)
                out = pathlib.Path(os.environ['TEST_CAPTURE']) / target.rsplit('/',1)[-1]
                out.mkdir(parents=True, exist_ok=True)
                commits[target] = subprocess.check_output([os.environ['TEST_REAL_GIT'], '-C', str(cwd), 'show', '-s', '--format=%H%n%P%n%B', source]).decode()
                tree = subprocess.check_output([os.environ['TEST_REAL_GIT'], '-C', str(cwd), 'ls-tree', '-rz', source])
                for entry in tree.split(b'\0'):
                    if not entry: continue
                    meta, rawpath = entry.split(b'\t', 1)
                    mode, kind, oid = meta.split()
                    path = out / rawpath.decode()
                    if kind != b'blob' or '..' in path.relative_to(out).parts: sys.exit('Unsafe capture')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(subprocess.check_output([os.environ['TEST_REAL_GIT'], '-C', str(cwd), 'cat-file', 'blob', oid.decode()]))
                    path.chmod(0o755 if mode == b'100755' else 0o644)
        pathlib.Path(os.environ['TEST_CAPTURE'], 'commits.json').write_text(json.dumps(commits))
        shutil.copytree(cwd / '.git/objects', pathlib.Path(os.environ['TEST_CAPTURE'], 'objects'), dirs_exist_ok=True)
    sys.exit(int(os.environ.get('TEST_'+cmd.upper()+'_EXIT', '0')))
allowed = {'init','config','remote','checkout','rev-parse','rebase','reset','status','add','diff','commit','log','show','branch','update-ref','ls-files','ls-tree','cat-file','read-tree','write-tree','commit-tree','merge-base','symbolic-ref','check-ref-format','var','rev-list'}
if cmd not in allowed: sys.exit('Blocked Git operation: '+cmd)
if cmd == 'remote' and (not rest or rest[0] not in ('get-url','add')): sys.exit('Blocked remote operation')
if stdin is not None:
    sys.exit(subprocess.run([os.environ['TEST_REAL_GIT'], *args], input=stdin).returncode)
os.execv(os.environ['TEST_REAL_GIT'], [os.environ['TEST_REAL_GIT'], *args])
'''


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ljg-publish-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.trace = self.base / "trace.jsonl"
        self.capture = self.base / "capture"
        self.hooks = self.base / "no-hooks"
        self.hooks.mkdir()
        self.env = {
            "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
            "PATH": str(self.bin) + os.pathsep + os.path.dirname(sys.executable) + ":/usr/bin:/bin",
            "LC_ALL": "C", "TZ": "UTC", "TMPDIR": str(self.base), "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": str(self.hooks),
            "GIT_CONFIG_KEY_1": "protocol.allow", "GIT_CONFIG_VALUE_1": "never",
            "GIT_CONFIG_KEY_2": "init.templateDir", "GIT_CONFIG_VALUE_2": "",
            "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "", "GIT_OPTIONAL_LOCKS": "0",
            "GIT_AUTHOR_NAME": "Publish Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Publish Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
            "TEST_ROOT": str(self.base), "TEST_TRACE": str(self.trace),
            "TEST_CAPTURE": str(self.capture), "TEST_REAL_GIT": REAL_GIT,
        }
        stub = self.bin / "git"
        stub.write_text("#!/usr/bin/env python3\n" + GIT_STUB)
        stub.chmod(0o755)
        self.repo = self.home / "code/ljg-skills"
        self.repo.mkdir(parents=True)
        self.local = self.home / ".agents/skills"
        (self.local / "ljg-test").mkdir(parents=True)
        (self.local / "ljg-test/SKILL.md").write_text("new skill\n")
        self.git("init", "-q", "-b", "master")
        self.git("config", "user.name", "Publish Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("remote", "add", "origin", ORIGIN)
        (self.repo / "skills/ljg-test").mkdir(parents=True)
        (self.repo / "skills/ljg-test/SKILL.md").write_text("old skill\n")
        (self.repo / "README.md").write_text("ljg-test\n")
        (self.repo / ".claude-plugin").mkdir()
        (self.repo / ".claude-plugin/plugin.json").write_text(json.dumps({"name": "ljg-skills", "version": "1.20.0"}) + "\n")
        (self.repo / ".claude-plugin/marketplace.json").write_text(json.dumps({"version": "1.20.0", "plugins": [{"name": "ljg-skills", "version": "1.20.0", "source": "./"}]}) + "\n")
        self.commit("baseline")
        self.git("branch", "md")
        self.refresh_remote()
        self.trace.unlink(missing_ok=True)

    def run_cmd(self, cmd, extra=None, check=False):
        result = subprocess.run(cmd, cwd=self.base, env={**self.env, **(extra or {})},
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout)
        return result

    def git(self, *args):
        return self.run_cmd([str(self.bin / "git"), "-C", str(self.repo), *args], check=True).stdout.strip()

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "-qm", message)

    def refresh_remote(self):
        refs = {name: self.git("rev-parse", name) for name in ("master", "md")}
        for name, oid in refs.items():
            self.git("update-ref", "refs/remotes/origin/" + name, oid)
        self.env["TEST_REMOTE_REFS"] = json.dumps(refs)

    def root_files(self, label):
        # Literal contract, independent of the publisher's own allowlist.
        return {
            "README.md": (0o644, "ljg-test\n" + label + "\n"),
            "CLAUDE.md": (0o644, label + " instructions\n"),
            "LICENSE": (0o644, label + " license\n"),
            ".gitignore": (0o644, "/scripts/ignored.py\n# " + label + "\n"),
            "scripts/setup.py": (0o755, "# " + label + " setup\n"),
            "scripts/check.py": (0o755, "# " + label + " check\n"),
            "scripts/install.sh": (0o755, "# " + label + " install\n"),
            "scripts/nested/helper.py": (0o644, "# " + label + " helper\n"),
            "docs/maintenance.md": (0o644, label + " guide\n"),
            ".github/workflows/check.yml": (0o644, "name: " + label + "\n"),
        }

    def write_roots(self, label):
        files = self.root_files(label)
        for relative, (mode, content) in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            path.chmod(mode)
        return files

    def assert_roots(self, branch, files):
        for relative, (mode, content) in files.items():
            path = self.capture / branch / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(path.read_text(), content, relative)
            self.assertEqual(path.stat().st_mode & 0o777, mode, relative)

    def adopt_capture(self):
        commits = json.loads((self.capture / "commits.json").read_text())
        # Import only captured local objects; never fetch or execute a transport.
        for child in (self.capture / "objects").iterdir():
            if len(child.name) == 2 and child.is_dir():
                shutil.copytree(child, self.repo / ".git/objects" / child.name, dirs_exist_ok=True)
        self.git("checkout", "--detach", "-q", "HEAD")
        for branch in ("master", "md"):
            self.git("branch", "-f", branch, commits["refs/heads/" + branch].splitlines()[0])
        self.git("checkout", "-q", "master")
        self.refresh_remote()
        shutil.rmtree(self.capture)

    def snapshot(self):
        return {str(p.relative_to(self.repo)): ("link", os.readlink(p)) if p.is_symlink()
                else (p.stat().st_mode, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in self.repo.rglob("*") if p.is_file() or p.is_symlink()}

    def calls(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def publish(self, *args, extra=None):
        return self.run_cmd(["/bin/bash", str(PUSH), "--repo", str(self.repo), "--local", str(self.local), *args], extra)

    def test_dry_run_dirty_preserves_head_index_and_files(self):
        (self.repo / "README.md").write_text("irreplaceable local edit\n")
        before = self.snapshot()
        result = self.publish("--dry-run", extra={"TEST_PULL_EXIT": "1"})
        self.assertEqual(self.snapshot(), before, result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(any(c["cmd"] in ("pull", "fetch", "push", "checkout", "reset") for c in self.calls()))

    def test_unrelated_untracked_file_is_not_committed(self):
        secret = self.repo / "skills/ljg-private/.env"
        secret.parent.mkdir()
        secret.write_text("FAKE_SECRET=not-real\n")
        before = self.snapshot()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(c["cmd"] == "push" for c in self.calls()))

    def test_version_mismatch_is_rejected(self):
        p = self.repo / ".claude-plugin/marketplace.json"
        data = json.loads(p.read_text()); data["plugins"][0]["version"] = "9.0.0"
        p.write_text(json.dumps(data)); self.commit("mismatched metadata"); self.refresh_remote()
        before = self.snapshot()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_manual_md_patch_is_preserved(self):
        self.git("checkout", "-q", "md")
        patch = self.repo / "skills/ljg-test/manual.md"
        patch.write_text("valuable manual patch\n"); self.commit("manual md patch")
        self.git("checkout", "-q", "master"); self.refresh_remote()
        before = self.snapshot()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(c["cmd"] == "push" for c in self.calls()))

    def test_clean_dry_run_is_completely_read_only(self):
        before = self.snapshot()
        dirs = sorted(str(p.relative_to(self.base)) for p in self.base.rglob("*") if p.is_dir())
        result = self.publish("--dry-run", "--force")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("DRY RUN", result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(dirs, sorted(str(p.relative_to(self.base)) for p in self.base.rglob("*") if p.is_dir()))
        self.assertFalse(any(c["cmd"] in ("push", "pull", "fetch", "ls-remote", "init", "add", "read-tree", "commit-tree", "checkout", "reset") for c in self.calls()))

    def test_atomic_publish_exact_scope_versions_and_parentage(self):
        (self.local / "ljg-test/SKILL.md").write_text("new source in org-mode\n")
        (self.local / "ljg-test/template.org").write_text("#+title: Test\n#+filetags: :test:\n\n* Heading\n[[file:image.png]]\n")
        (self.local / "ljg-test/test.ts").write_text('load("template.org")\n')
        before = self.snapshot()
        result = self.publish("--skill", "ljg-test")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.snapshot(), before)
        pushes = [c for c in self.calls() if c["cmd"] == "push"]
        self.assertEqual(len(pushes), 1)
        self.assertIn("--atomic", pushes[0]["args"])
        self.assertIn("origin", pushes[0]["args"])
        for branch in ("master", "md"):
            self.assertTrue(any(a.endswith(":refs/heads/" + branch) and not a.startswith("-") for a in pushes[0]["args"]))
            captured = self.capture / branch
            self.assertEqual(json.loads((captured / ".claude-plugin/plugin.json").read_text())["version"], "1.20.1")
            market = json.loads((captured / ".claude-plugin/marketplace.json").read_text())
            self.assertEqual([market["version"], market["plugins"][0]["version"]], ["1.20.1"] * 2)
            self.assertEqual((captured / "README.md").read_text(), "ljg-test\n")
        self.assertTrue((self.capture / "master/skills/ljg-test/template.org").exists())
        self.assertFalse((self.capture / "md/skills/ljg-test/template.org").exists())
        self.assertIn("# Heading", (self.capture / "md/skills/ljg-test/template.md").read_text())
        self.assertIn("template.md", (self.capture / "md/skills/ljg-test/test.ts").read_text())
        self.assertIn("markdown", (self.capture / "md/skills/ljg-test/SKILL.md").read_text())
        commits = json.loads((self.capture / "commits.json").read_text())
        source = commits["refs/heads/master"].splitlines()[0]
        self.assertIn(source, commits["refs/heads/md"].splitlines()[1].split())
        self.assertIn("LJG-Source: " + source, commits["refs/heads/md"])
        staged = [c for c in self.calls() if c["cmd"] == "add"]
        self.assertTrue(staged)
        for call in staged:
            self.assertIn("--pathspec-from-file=-", call["args"])
            self.assertIn("--pathspec-file-nul", call["args"])
            self.assertTrue(call["paths"])
            for path in call["paths"]:
                self.assertTrue(path.startswith("skills/ljg-test/") or path in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"), path)
        self.assertFalse(any(c["cmd"] in ("pull", "fetch", "reset", "checkout") for c in self.calls()))

    def test_missing_md_branch_created_from_new_source(self):
        self.git("branch", "-D", "md")
        self.git("update-ref", "-d", "refs/remotes/origin/md")
        self.env["TEST_REMOTE_REFS"] = json.dumps({"master": self.git("rev-parse", "master")})
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        commits = json.loads((self.capture / "commits.json").read_text())
        source = commits["refs/heads/master"].splitlines()[0]
        self.assertEqual(commits["refs/heads/md"].splitlines()[1], source)

    def test_noop_does_not_bump_or_network(self):
        (self.local / "ljg-test/SKILL.md").write_text("old skill\n")
        before = self.snapshot()
        result = self.publish("--force")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Nothing to push", result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(c["cmd"] in ("push", "ls-remote") for c in self.calls()))

    def test_new_md_inherits_committed_root_tools_and_modes(self):
        roots = self.write_roots("safe source")
        self.commit("source root tools")
        self.git("branch", "-D", "md")
        self.git("update-ref", "-d", "refs/remotes/origin/md")
        source = self.git("rev-parse", "master")
        self.env["TEST_REMOTE_REFS"] = json.dumps({"master": source})
        (self.repo / "scripts/ignored.py").write_text("uncommitted local tool\n")
        before = self.snapshot()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.snapshot(), before)
        for branch in ("master", "md"):
            self.assert_roots(branch, roots)
            self.assertFalse((self.capture / branch / "scripts/ignored.py").exists())

    def test_existing_md_syncs_root_only_add_edit_delete_without_version_bump(self):
        self.write_roots("old source")
        (self.repo / "scripts/retired.py").write_text("retired tool\n")
        self.commit("source root baseline")
        self.git("branch", "-f", "md", "master"); self.refresh_remote()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.adopt_capture()
        old_md = self.git("rev-parse", "md")
        roots = self.write_roots("safe source")
        roots["scripts/check.py"] = (0o644, roots["scripts/check.py"][1])
        (self.repo / "scripts/check.py").chmod(0o644)
        (self.repo / "scripts/retired.py").unlink()
        roots["scripts/new.py"] = (0o644, "new safe tool\n")
        (self.repo / "scripts/new.py").write_text(roots["scripts/new.py"][1])
        # Out-of-scope source-only paths must not be added to an existing md.
        for relative in ("private.txt", "docs-extra/secret.txt", ".claude-plugin/unmanaged.json"):
            path = self.repo / relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not a managed root path\n")
        self.commit("root-only safety update"); self.refresh_remote()
        source = self.git("rev-parse", "master")
        (self.repo / "scripts/ignored.py").write_text("uncommitted local tool\n")
        before = self.snapshot()
        self.trace.unlink()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("Nothing to push", result.stdout)
        self.assertIn("Version: 1.20.1 -> 1.20.1", result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assert_roots("md", roots)
        for relative in ("scripts/retired.py", "scripts/ignored.py", "private.txt", "docs-extra/secret.txt", ".claude-plugin/unmanaged.json"):
            self.assertFalse((self.capture / "md" / relative).exists(), relative)
        commits = json.loads((self.capture / "commits.json").read_text())
        self.assertEqual(commits["refs/heads/master"].splitlines()[0], source)
        self.assertEqual(commits["refs/heads/md"].splitlines()[1].split(), [old_md, source])
        self.assertIn("LJG-Source: " + source, commits["refs/heads/md"])
        for branch in ("master", "md"):
            self.assertEqual(json.loads((self.capture / branch / ".claude-plugin/plugin.json").read_text())["version"], "1.20.1")
        pushes = [c for c in self.calls() if c["cmd"] == "push"]
        self.assertEqual(len(pushes), 1)
        self.assertIn("--atomic", pushes[0]["args"])
        self.assertIn("--force-with-lease=refs/heads/master:" + source, pushes[0]["args"])
        self.assertIn("--force-with-lease=refs/heads/md:" + old_md, pushes[0]["args"])
        self.adopt_capture(); self.trace.unlink()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Nothing to push", result.stdout)
        self.assertFalse(any(c["cmd"] in ("push", "ls-remote") for c in self.calls()))

    def test_root_only_dry_run_lists_committed_changes_without_writes_or_network(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.adopt_capture()
        roots = self.write_roots("safe source"); self.commit("root tools"); self.refresh_remote()
        before = self.snapshot()
        dirs = sorted(str(p.relative_to(self.base)) for p in self.base.rglob("*") if p.is_dir())
        self.trace.unlink()
        result = self.publish("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout)
        for relative in roots:
            self.assertIn("  md: " + relative, result.stdout)
        self.assertIn("Version: 1.20.1 -> 1.20.1", result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(dirs, sorted(str(p.relative_to(self.base)) for p in self.base.rglob("*") if p.is_dir()))
        self.assertFalse(any(c["cmd"] in ("push", "ls-remote", "init", "add", "read-tree", "commit-tree") for c in self.calls()))

    def test_marked_md_root_drift_rejected_for_every_managed_root(self):
        self.write_roots("baseline"); self.commit("root baseline")
        self.git("branch", "-f", "md", "master"); self.refresh_remote()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.adopt_capture()
        good_md = self.git("rev-parse", "md")
        base = self.git("rev-parse", "master")
        for relative in self.root_files("baseline"):
            self.git("branch", "-f", "md", good_md)
            if self.capture.exists():
                shutil.rmtree(self.capture)
            with self.subTest(path=relative):
                self.git("checkout", "-q", "md")
                path = self.repo / relative
                path.write_text(path.read_text() + "manual md patch\n")
                # Retain a valid direct-parent marker; refusal must detect roots,
                # not reject a malformed marker or fall back to legacy checking.
                self.git("add", "--all")
                tree = self.git("write-tree")
                drifted = self.git("commit-tree", tree, "-p", good_md, "-p", base, "-m", "manual\n\nLJG-Source: " + base)
                self.git("update-ref", "refs/heads/md", drifted)
                self.git("checkout", "-q", "master"); self.refresh_remote()
                before = self.snapshot(); self.trace.unlink()
                result = self.publish()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("Unmanaged Markdown root differences", result.stdout)
                self.assertIn(relative, result.stdout)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(any(c["cmd"] in ("push", "ls-remote", "commit-tree") for c in self.calls()))
                self.git("branch", "-f", "md", good_md)

    def test_legacy_md_root_edit_add_delete_and_mode_drift_refused(self):
        self.write_roots("baseline"); self.commit("root baseline")
        self.git("branch", "-f", "md", "master"); self.refresh_remote()
        baseline = self.git("rev-parse", "md")
        for kind in ("edit", "add", "delete", "mode"):
            self.git("branch", "-f", "md", baseline)
            if self.capture.exists():
                shutil.rmtree(self.capture)
            with self.subTest(kind=kind):
                self.git("checkout", "-q", "md")
                path = self.repo / "scripts/check.py"
                if kind == "edit":
                    path.write_text("manual md patch\n")
                elif kind == "add":
                    path = self.repo / "scripts/manual.py"; path.write_text("manual md tool\n")
                elif kind == "delete":
                    path.unlink()
                else:
                    path.chmod(0o644)
                self.commit("legacy manual " + kind)
                self.git("checkout", "-q", "master"); self.refresh_remote()
                before = self.snapshot(); self.trace.unlink()
                result = self.publish()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("Unmanaged Markdown root differences", result.stdout)
                self.assertIn(str(path.relative_to(self.repo)), result.stdout)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(any(c["cmd"] in ("push", "ls-remote", "commit-tree") for c in self.calls()))
                self.git("branch", "-f", "md", baseline)

    def test_legacy_md_missing_source_root_tools_requires_explicit_migration(self):
        self.write_roots("safe source"); self.commit("new source root tools"); self.refresh_remote()
        before = self.snapshot(); self.trace.unlink()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Unmanaged Markdown root differences", result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(c["cmd"] in ("push", "ls-remote", "commit-tree") for c in self.calls()))

    def test_unmanaged_target_root_is_preserved_not_replaced(self):
        path = self.repo / "private.txt"
        path.write_text("source root\n"); self.commit("unmanaged source root")
        self.git("checkout", "-q", "md")
        path.write_text("manual md root\n"); self.commit("unmanaged md root")
        self.git("checkout", "-q", "master"); self.refresh_remote()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.capture / "master/private.txt").read_text(), "source root\n")
        self.assertEqual((self.capture / "md/private.txt").read_text(), "manual md root\n")

    def test_source_and_target_root_symlinks_refused(self):
        for branch in ("master", "md"):
            with self.subTest(branch=branch):
                self.git("checkout", "-q", branch)
                path = self.repo / "docs/link.md"; path.parent.mkdir(exist_ok=True)
                path.symlink_to("../README.md")
                self.commit("root symlink"); self.git("checkout", "-q", "master"); self.refresh_remote()
                before = self.snapshot(); self.trace.unlink()
                result = self.publish("--dry-run")
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("Symlink/submodule/non-regular tracked path: docs/link.md", result.stdout)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(any(c["cmd"] in ("push", "ls-remote", "init") for c in self.calls()))
                self.git("checkout", "-q", branch)
                path.unlink(); self.commit("remove test symlink")
                self.git("checkout", "-q", "master"); self.refresh_remote()

    def test_committed_readback_includes_roots_and_rejects_corruption(self):
        module = self.load_publisher()
        self.write_roots("safe source"); self.commit("root tools")
        self.git("branch", "-f", "md", "master"); self.refresh_remote()
        arguments = module.args_parser().parse_args(["--repo", str(self.repo), "--local", str(self.local)])
        original = module.read_tree_with_env
        seen = []
        def corrupted(build, commit, env):
            result = original(build, commit, env)
            seen.append(set(result))
            if "scripts/check.py" in result:
                result["scripts/check.py"] = ("100755", b"corrupted committed tool\n")
            return result
        before = self.snapshot(); self.trace.unlink()
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(tempfile, "tempdir", str(self.base)), mock.patch.object(module, "read_tree_with_env", corrupted), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(module.Refusal, "Committed managed tree differs"):
                module.publish(arguments)
        self.assertTrue(any("scripts/check.py" in paths for paths in seen))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(c["cmd"] == "push" for c in self.calls()))
        self.assertFalse(list(self.base.glob("ljg-publish-*")))

    def test_compatibility_skill_selected_and_tracked_with_exact_readme_name(self):
        name = "fix-ljg-org-to-md"
        source = self.local / name; source.mkdir()
        (source / "SKILL.md").write_text("Format-neutral maintenance skill.\n")
        (self.repo / "README.md").write_text("ljg-test\n" + name + "\n")
        self.commit("document maintenance skill"); self.git("branch", "-f", "md", "master"); self.refresh_remote()
        result = self.publish("--skill", name)
        self.assertEqual(result.returncode, 0, result.stdout)
        for branch in ("master", "md"):
            self.assertEqual((self.capture / branch / "skills" / name / "SKILL.md").read_bytes(), (source / "SKILL.md").read_bytes())
        self.adopt_capture()
        (self.local / "ljg-test/SKILL.md").write_text("old skill\n")
        (source / "SKILL.md").write_text("Updated maintenance skill.\n")
        result = self.publish()  # Default discovery must include the exact exception.
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Skills: fix-ljg-org-to-md, ljg-test", result.stdout)
        self.assertIn("Version: 1.20.1 -> 1.20.2", result.stdout)
        self.assertEqual((self.capture / "md/skills" / name / "SKILL.md").read_bytes(), (source / "SKILL.md").read_bytes())

    def test_compatibility_skill_readme_and_path_guards_remain_exact(self):
        name = "fix-ljg-org-to-md"
        source = self.local / name; source.mkdir()
        (source / "SKILL.md").write_text("Format-neutral maintenance skill.\n")
        for listed in ("ljg-org-to-md", "fix-ljg-org-to-md-extra", "prefix-fix-ljg-org-to-md"):
            with self.subTest(listed=listed):
                (self.repo / "README.md").write_text("ljg-test\n" + listed + "\n")
                self.commit("near-match documentation"); self.git("branch", "-f", "md", "master"); self.refresh_remote()
                result = self.publish("--skill", name)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("README missing skills: " + name, result.stdout)
        for invalid in ("fix-ljg-other", "fix-ljg-org-to-md-extra", "../fix-ljg-org-to-md", "fix-ljg-org-to-md/../../outside"):
            with self.subTest(invalid=invalid):
                result = self.publish("--dry-run", "--skill", invalid)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("Invalid skill name", result.stdout)
        self.assertFalse(any(c["cmd"] in ("push", "ls-remote") for c in self.calls()))

    def test_publisher_import_has_no_process_or_filesystem_side_effects(self):
        # Copy imports to the fixture so a failed import test cannot write real repo files.
        tools = self.base / "import tools"; tools.mkdir()
        for name in ("publish.py", "markdown.py"):
            shutil.copyfile(PUSH.parent / name, tools / name)
        script = '''import importlib.util, os, pathlib, subprocess, sys, tempfile
sys.path.insert(0, sys.argv[1])
before = (sys.dont_write_bytecode, list(sys.path), dict(os.environ))
def forbidden(*args, **kwargs):
    raise AssertionError("publisher import performed I/O")
subprocess.run = forbidden
subprocess.Popen = forbidden
tempfile.TemporaryDirectory = forbidden
spec = importlib.util.spec_from_file_location("imported_publisher", pathlib.Path(sys.argv[1]) / "publish.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert before == (sys.dont_write_bytecode, list(sys.path), dict(os.environ)), "publisher import changed process settings"
'''
        self.trace.unlink(missing_ok=True)
        result = self.run_cmd([sys.executable, "-B", "-c", script, str(tools)], extra={"PYTHONDONTWRITEBYTECODE": ""})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(list(tools.rglob("__pycache__")))
        # Repeat without -B to detect global bytecode-policy changes. The only
        # permitted writes here are Python's normal cache inside this fixture.
        result = self.run_cmd([sys.executable, "-c", script, str(tools)], extra={"PYTHONDONTWRITEBYTECODE": ""})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.calls())

    def test_git_stub_executes_with_space_in_virtualenv_interpreter_path(self):
        venv = self.base / "space in venv"
        self.run_cmd([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
        python = venv / "bin/python3"
        result = self.run_cmd([str(python), "-B", "-c",
                               "import sys, unittest; sys.path.insert(0, sys.argv[1]); "
                               "import test_publish; test_publish.REAL_GIT = sys.argv[2]; "
                               "suite=unittest.TestSuite([test_publish.PublishTests('test_clean_dry_run_is_completely_read_only')]); "
                               "sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())", str(ROOT / "scripts"), REAL_GIT])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_staged_changes_rejected(self):
        (self.repo / "README.md").write_text("ljg-test\nstaged unrelated work\n")
        self.git("add", "README.md")
        before = self.snapshot()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Dirty worktree/index", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_wrong_origin_is_exact_not_substring(self):
        self.git("config", "remote.origin.url", ORIGIN + "-lookalike")
        before = self.snapshot()
        result = self.publish("--dry-run")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Unexpected origin", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_explicit_origin_override_and_pushurl_mismatch(self):
        self.git("config", "remote.origin.url", "https://example.invalid/approved.git")
        result = self.publish("--dry-run", "--origin", "https://example.invalid/approved.git")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.git("config", "remote.origin.pushurl", "https://example.invalid/wrong.git")
        result = self.publish("--dry-run", "--origin", "https://example.invalid/approved.git")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("identical fetch/push", result.stdout)

    def test_remote_moved_refuses_before_build(self):
        before = self.snapshot()
        result = self.publish(extra={"TEST_REMOTE_REFS": json.dumps({"master": "a" * 40, "md": self.git("rev-parse", "md")})})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Remote/local ref mismatch", result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(c["cmd"] in ("push", "pull", "fetch", "commit-tree") for c in self.calls()))

    def test_push_failure_has_no_local_changes_or_success_message(self):
        before = self.snapshot()
        result = self.publish(extra={"TEST_PUSH_EXIT": "1"})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("Published atomically", result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len([c for c in self.calls() if c["cmd"] == "push"]), 1)
        self.assertFalse(list(self.base.glob("ljg-publish-*")))

    def test_source_symlinks_rejected(self):
        outside = self.base / "outside.txt"; outside.write_text("precious\n")
        (self.local / "ljg-test/escape.txt").symlink_to(outside)
        before = self.snapshot()
        result = self.publish("--dry-run")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Symlink", result.stdout)
        self.assertEqual(outside.read_text(), "precious\n")
        self.assertEqual(self.snapshot(), before)

    def test_source_root_symlink_and_hardlink_rejected(self):
        alias = self.base / "source-alias"
        alias.symlink_to(self.local, target_is_directory=True)
        result = self.publish("--dry-run", "--local", str(alias))
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("symlink component", result.stdout)
        outside = self.base / "hardlinked-file"; outside.write_text("outside\n")
        os.link(outside, self.local / "ljg-test/linked.txt")
        result = self.publish("--dry-run")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("hard-linked", result.stdout)
        self.assertEqual(outside.read_text(), "outside\n")

    def test_missing_repo_is_not_created_or_cloned(self):
        missing = self.base / "missing-repo"
        result = self.publish("--repo", str(missing), "--dry-run")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(missing.exists())
        self.assertFalse(any(c["cmd"] in ("clone", "fetch", "pull", "push") for c in self.calls()))

    def test_source_directory_symlink_rejected(self):
        (self.local / "ljg-test").rename(self.base / "outside-skill")
        (self.local / "ljg-test").symlink_to(self.base / "outside-skill", target_is_directory=True)
        result = self.publish("--dry-run")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("without symlinks", result.stdout)

    def test_tracked_destination_symlink_rejected(self):
        target = self.repo / "skills/ljg-test/SKILL.md"
        target.unlink(); target.symlink_to(self.base / "outside.md")
        self.commit("symlink"); self.refresh_remote()
        before = self.snapshot()
        result = self.publish("--dry-run")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Symlink", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_skill_names_reject_paths_and_options(self):
        for name in ("../../outside", "ljg-a/../../outside", "ljg-x\\outside", "ljg-a*", "-x", "ljg-", "ljg-a\nb"):
            with self.subTest(name=name):
                result = self.publish("--dry-run", "--skill=" + name)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("Invalid skill name", result.stdout)
        self.assertFalse(any(c["cmd"] in ("push", "pull", "fetch") for c in self.calls()))

    def test_org_md_collision_is_rejected(self):
        (self.local / "ljg-test/template.org").write_text("* Title\n")
        (self.local / "ljg-test/template.md").write_text("manual work\n")
        before = self.snapshot()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("collision", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_json_keys_rejected(self):
        (self.repo / ".claude-plugin/plugin.json").write_text('{"name":"ljg-skills","version":"1.20.0","version":"1.20.0"}')
        self.commit("duplicate key"); self.refresh_remote()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Duplicate JSON key", result.stdout)

    def test_legacy_wrapper_publishes_with_same_guards(self):
        result = self.legacy("ljg-test", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("DRY RUN", result.stdout)
        self.assertFalse(any(c["cmd"] in ("push", "pull", "fetch", "ls-remote") for c in self.calls()))

    def test_fsmonitor_and_hooks_never_execute(self):
        marker = self.base / "hook-executed"
        hook = self.base / "malicious-hook"
        hook.write_text('#!/bin/sh\nprintf BAD > "' + str(marker) + '"\nexit 1\n')
        hook.chmod(0o755)
        self.git("config", "core.fsmonitor", str(hook))
        for name in ("pre-commit", "pre-push", "post-checkout"):
            script = self.repo / ".git/hooks" / name
            script.parent.mkdir(exist_ok=True)
            shutil.copyfile(hook, script); script.chmod(0o755)
        before = self.snapshot()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(marker.exists())
        self.assertEqual(self.snapshot(), before)

    def test_git_environment_redirect_rejected(self):
        result = self.publish("--dry-run", extra={"GIT_INDEX_FILE": str(self.base / "redirected-index")})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("redirected Git environment", result.stdout)
        self.assertFalse((self.base / "redirected-index").exists())

    def test_assume_unchanged_hidden_dirty_file_rejected(self):
        self.run_cmd([REAL_GIT, "-C", str(self.repo), "update-index", "--assume-unchanged", "README.md"], check=True)
        (self.repo / "README.md").write_text("hidden work\n")
        before = self.snapshot()
        result = self.publish("--dry-run")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("assume-unchanged/skip-worktree", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_skill_deletion_is_explicitly_staged(self):
        (self.repo / "skills/ljg-test/old.txt").write_text("remove from source\n")
        self.commit("old file"); self.git("branch", "-f", "md", "master"); self.refresh_remote()
        self.trace.unlink()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        for branch in ("master", "md"):
            self.assertFalse((self.capture / branch / "skills/ljg-test/old.txt").exists())
        self.assertTrue(any("skills/ljg-test/old.txt" in c["paths"] for c in self.calls() if c["cmd"] == "add"))

    def test_recorded_md_source_republishes_then_rejects_manual_drift(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        commits = json.loads((self.capture / "commits.json").read_text())
        source = commits["refs/heads/master"].splitlines()[0]
        md = commits["refs/heads/md"].splitlines()[0]
        # Import captured local objects only; this is not a fetch or network transport.
        objects = self.capture / "objects"
        for child in objects.iterdir():
            if len(child.name) == 2 and child.is_dir():
                shutil.copytree(child, self.repo / ".git/objects" / child.name, dirs_exist_ok=True)
        self.git("checkout", "--detach", "-q", "HEAD")
        self.git("branch", "-f", "master", source); self.git("branch", "-f", "md", md)
        self.git("checkout", "-q", "master"); self.refresh_remote()
        shutil.rmtree(self.capture)
        result = self.publish("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Version: 1.20.1 -> 1.20.1", result.stdout)
        (self.local / "ljg-test/SKILL.md").write_text("second source change\n")
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("version 1.20.2", result.stdout)
        self.git("checkout", "-q", "md")
        (self.repo / "skills/ljg-test/SKILL.md").write_text("manual md edit\n")
        self.commit("manual md drift"); self.git("checkout", "-q", "master"); self.refresh_remote()
        before = self.snapshot()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Unmanaged Markdown differences", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_other_plugin_version_unchanged(self):
        path = self.repo / ".claude-plugin/marketplace.json"
        value = json.loads(path.read_text())
        value["plugins"].append({"name": "other", "version": "7.8.9", "source": "./other"})
        path.write_text(json.dumps(value)); self.commit("other plugin")
        self.git("branch", "-f", "md", "master"); self.refresh_remote()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        for branch in ("master", "md"):
            data = json.loads((self.capture / branch / ".claude-plugin/marketplace.json").read_text())
            self.assertEqual(data["plugins"][1]["version"], "7.8.9")

    def test_unreadable_source_directory_aborts_instead_of_deleting(self):
        protected = self.repo / "skills/ljg-test/protected/keep.txt"
        protected.parent.mkdir(); protected.write_text("must survive\n")
        self.commit("protected source file"); self.git("branch", "-f", "md", "master"); self.refresh_remote()
        source = self.local / "ljg-test/protected"
        source.mkdir(); (source / "keep.txt").write_text("must survive\n")
        module = self.load_publisher()
        arguments = module.args_parser().parse_args(["--repo", str(self.repo), "--local", str(self.local)])
        real_scandir = os.scandir
        def unreadable(path):
            if not isinstance(path, int) and Path(path) == source:
                raise PermissionError("injected unreadable skill directory")
            return real_scandir(path)
        before = self.snapshot()
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(tempfile, "tempdir", str(self.base)), mock.patch.object(os, "scandir", unreadable), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex((OSError, module.Refusal), "unreadable skill directory"):
                module.publish(arguments)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(c["cmd"] == "push" for c in self.calls()))

    def test_legacy_md_nonversion_metadata_must_not_be_overwritten(self):
        self.git("checkout", "-q", "md")
        path = self.repo / ".claude-plugin/marketplace.json"
        value = json.loads(path.read_text()); value["description"] = "manual md metadata"
        value["plugins"].append({"name": "md-extra", "version": "3.4.5", "source": "./md-extra"})
        path.write_text(json.dumps(value)); self.commit("md manual metadata")
        self.git("checkout", "-q", "master"); self.refresh_remote()
        before = self.snapshot()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Unmanaged Markdown metadata", result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(c["cmd"] == "push" for c in self.calls()))

    def test_legacy_md_allows_only_the_three_release_version_differences(self):
        self.git("checkout", "-q", "md")
        for filename in ("plugin.json", "marketplace.json"):
            path = self.repo / ".claude-plugin" / filename
            data = json.loads(path.read_text()); data["version"] = "1.19.0"
            if filename == "marketplace.json":
                data["plugins"][0]["version"] = "1.19.0"
            path.write_text(json.dumps(data))
        self.commit("old release version"); self.git("checkout", "-q", "master"); self.refresh_remote()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads((self.capture / "md/.claude-plugin/marketplace.json").read_text())
        self.assertEqual([data["version"], data["plugins"][0]["version"]], ["1.20.1"] * 2)

    def test_file_to_directory_and_back_publish_on_both_branches(self):
        old = self.repo / "skills/ljg-test/guide"
        old.write_text("old file\n"); self.commit("file baseline")
        self.git("branch", "-f", "md", "master"); self.refresh_remote()
        new = self.local / "ljg-test/guide"
        new.mkdir(); (new / "intro.md").write_text("new directory\n")
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        for branch in ("master", "md"):
            self.assertEqual((self.capture / branch / "skills/ljg-test/guide/intro.md").read_text(), "new directory\n")
        # New independent clean baseline for the reverse transition, no network.
        old.unlink(); old.mkdir(); (old / "intro.md").write_text("old directory\n")
        self.commit("directory baseline"); self.git("branch", "-f", "md", "master"); self.refresh_remote()
        shutil.rmtree(new); new.write_text("new file\n"); shutil.rmtree(self.capture)
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        for branch in ("master", "md"):
            self.assertEqual((self.capture / branch / "skills/ljg-test/guide").read_text(), "new file\n")

    def assert_root_shape_swap_over_batch_boundary(self, directory_to_file):
        target = self.repo / "scripts/guide"
        target.parent.mkdir()
        if directory_to_file:
            target.mkdir(); (target / "page.txt").write_text("old page\n")
        else:
            target.write_text("old file\n")
        self.commit("root shape baseline")
        self.git("branch", "-f", "md", "master"); self.refresh_remote()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.adopt_capture()
        if directory_to_file:
            shutil.rmtree(target); target.write_text("new file\n")
        else:
            target.unlink(); target.mkdir(); (target / "page.txt").write_text("new page\n")
        docs = self.repo / "docs"; docs.mkdir()
        # 99 docs plus the old/new shape paths = 101 changed paths. The old
        # 100-path batching staged scripts/guide before its deleted child.
        doc_names = [f"docs/page-{i:03d}.md" for i in range(97)] + ["docs/a space.md", "docs/literal[?]*.md"]
        for relative in doc_names:
            (self.repo / relative).write_text(relative + "\n")
        self.commit("root shape swap over batch boundary"); self.refresh_remote()
        before = self.snapshot(); self.trace.unlink()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("Version: 1.20.1 -> 1.20.1", result.stdout)
        for branch in ("master", "md"):
            output = self.capture / branch / "scripts/guide"
            if directory_to_file:
                self.assertTrue(output.is_file())
                self.assertEqual(output.read_text(), "new file\n")
            else:
                self.assertTrue(output.is_dir())
                self.assertEqual((output / "page.txt").read_text(), "new page\n")
            for relative in doc_names:
                self.assertEqual((self.capture / branch / relative).read_text(), relative + "\n")
        staged = [c for c in self.calls() if c["cmd"] == "add"]
        self.assertEqual(len(staged), 1)
        self.assertIn("--pathspec-from-file=-", staged[0]["args"])
        self.assertIn("--pathspec-file-nul", staged[0]["args"])
        paths = [path for call in staged for path in call["paths"]]
        self.assertEqual(sorted(paths), sorted([*doc_names, "scripts/guide", "scripts/guide/page.txt"]))

    def test_root_directory_to_file_with_over_100_changes(self):
        self.assert_root_shape_swap_over_batch_boundary(directory_to_file=True)

    def test_root_file_to_directory_with_over_100_changes(self):
        self.assert_root_shape_swap_over_batch_boundary(directory_to_file=False)

    def load_publisher(self):
        tools = PUSH.parent
        sys.path.insert(0, str(tools))
        self.addCleanup(lambda: sys.path.remove(str(tools)))
        spec = importlib.util.spec_from_file_location("publish_under_test", tools / "publish.py")
        module = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "dont_write_bytecode", True):
            spec.loader.exec_module(module)
        return module

    def test_write_failure_or_corruption_prevents_push(self):
        module = self.load_publisher()
        arguments = module.args_parser().parse_args(["--repo", str(self.repo), "--local", str(self.local)])
        original = Path.write_bytes
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                def failing_write(path, data):
                    if path.name == "plugin.json" and "build" in path.parts:
                        if not corrupt:
                            raise OSError("injected write failure")
                        return original(path, b"{}")
                    return original(path, data)
                before = self.snapshot()
                with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(tempfile, "tempdir", str(self.base)), mock.patch.object(Path, "write_bytes", failing_write), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex((OSError, module.Refusal), "injected write failure|Write readback failed"):
                        module.publish(arguments)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(any(c["cmd"] == "push" for c in self.calls()))
                self.assertFalse(list(self.base.glob("ljg-publish-*")))

    def legacy(self, skill="ljg-test", *args):
        repo = self.home / ".claude/ljg-skills-repo"
        repo.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.repo), str(repo)); self.repo = repo
        local = self.home / ".claude/skills"
        shutil.move(str(self.local), str(local)); self.local = local
        return self.run_cmd(["/bin/bash", str(SYNC), skill, "fixture publish", *args])

    def test_legacy_path_traversal_rejected(self):
        source = self.home / "outside"; source.mkdir()
        (source / "incoming.txt").write_text("incoming\n")
        target = self.home / ".claude/outside"; target.mkdir(parents=True)
        keep = target / "unique.txt"; keep.write_text("irreplaceable\n")
        result = self.legacy("../../outside")
        self.assertTrue(keep.exists(), result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse((target / "incoming.txt").exists())

    def test_legacy_wrong_branch_rejected(self):
        self.git("checkout", "-qb", "feature/work-in-progress")
        before = self.snapshot()
        result = self.legacy()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
