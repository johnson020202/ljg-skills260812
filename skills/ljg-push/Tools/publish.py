#!/usr/bin/env python3
"""Fail-closed dual-branch publisher. The input repository and skills are read-only."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile

# Direct CLI execution remains read-only even without -B; importing this module
# must not alter the caller's bytecode policy. Push.sh already invokes python -B.
if __name__ == "__main__":
    sys.dont_write_bytecode = True
from markdown import mdize

IDENTITY = "johnson020202/ljg-skills260812"
ORIGINS = {"https://github.com/" + IDENTITY, "https://github.com/" + IDENTITY + ".git",
           "git@github.com:" + IDENTITY + ".git", "ssh://git@github.com/" + IDENTITY + ".git"}
METADATA = (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json")
# Literal Git paths, not globs: the last three recurse into committed regular
# files only. Keep this contract usable by builders without importing this CLI.
ROOT_PATHS = ("README.md", "CLAUDE.md", "LICENSE", ".gitignore", "scripts", "docs", ".github")
ROOT_DIRECTORIES = frozenset({"scripts", "docs", ".github"})
COMPATIBLE_SKILL_NAMES = frozenset({"fix-ljg-org-to-md"})
NAME = re.compile(r"ljg-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
EXCLUDED = {".git", "node_modules", "__pycache__", ".DS_Store"}


class Refusal(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def git(repo, *args, env=None, data=None, check=True):
    read_env = {**(os.environ if env is None else env), "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"}
    result = subprocess.run(["git", "--no-optional-locks", "--literal-pathspecs",
                             "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
                             "-c", "core.untrackedCache=false", "-C", str(repo), *args],
                            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=read_env, timeout=120)
    if check and result.returncode:
        raise Refusal("git " + " ".join(args[:3]) + " failed: " + result.stderr.decode(errors="replace").strip())
    return result


def text(repo, *args, **kwargs):
    return git(repo, *args, **kwargs).stdout.decode("utf-8").strip()


def no_redirected_git():
    # A caller-supplied alternate index/worktree must not change the inspected repo.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_SHALLOW_FILE"):
        require(key not in os.environ, "Unset redirected Git environment: " + key)


def directory(value, label):
    path = Path(os.path.abspath(os.path.expanduser(value)))
    # Check lexical components too: resolve() alone would hide a symlink escape.
    for part in (path, *path.parents):
        require(not part.is_symlink(), label + " has a symlink component: " + str(part))
    require(path.is_dir(), label + " does not exist; clone/setup it explicitly: " + str(path))
    return path.resolve()


def clean_repo(repo, source_branch):
    require(Path(text(repo, "rev-parse", "--show-toplevel")).resolve() == repo, "--repo must be the repository root")
    require(text(repo, "symbolic-ref", "--quiet", "--short", "HEAD") == source_branch,
            "Wrong branch: check out " + source_branch + " yourself before publishing")
    require(not text(repo, "config", "--get-regexp", r"^(filter\..*\.(clean|smudge|process)|core\.attributesfile|extensions\.partialclone|remote\..*\.promisor)$", check=False),
            "External filters/attributes or partial clone can execute commands/fetch while reading; use a full clean publish clone")
    gitdir = Path(text(repo, "rev-parse", "--absolute-git-dir"))
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer", "index.lock"):
        require(not (gitdir / marker).exists(), "Git operation in progress: " + marker)
    require(not text(repo, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"),
            "Dirty worktree/index: commit or move your own changes first; nothing was synchronized")
    flags = text(repo, "ls-files", "-v").splitlines()
    require(not any(line and (line[0].islower() or line[0] == "S") for line in flags),
            "assume-unchanged/skip-worktree entries hide changes; clear them before publishing")


def origin_url(repo, expected):
    fetch = text(repo, "remote", "get-url", "--all", "origin").splitlines()
    push = text(repo, "remote", "get-url", "--push", "--all", "origin").splitlines()
    require(len(fetch) == len(push) == 1 and fetch == push,
            "origin must have one identical fetch/push URL (including URL rewrites)")
    require(fetch[0] in ({expected} if expected else ORIGINS),
            "Unexpected origin: " + fetch[0] + "; use --origin only for an explicitly approved exact URL")
    require(not fetch[0].startswith("-"), "Invalid origin URL")
    return fetch[0]


def oid(repo, ref, optional=False):
    result = git(repo, "rev-parse", "--verify", ref + "^{commit}", check=not optional)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def safe_tree_path(path):
    parts = PurePosixPath(path).parts
    require(parts and not path.startswith("/") and all(p not in ("", ".", "..", ".git") for p in parts)
            and "\\" not in path and not any(ord(c) < 32 for c in path), "Unsafe tree path: " + repr(path))


def read_tree(repo, ref, *paths, env=None):
    result = {}
    records = git(repo, "ls-tree", "-rz", ref, "--", *paths, env=env).stdout
    for entry in records.split(b"\0"):
        if not entry:
            continue
        meta, rawpath = entry.split(b"\t", 1)
        mode, kind, object_id = meta.decode().split()
        path = rawpath.decode("utf-8")
        safe_tree_path(path)
        require(mode in ("100644", "100755") and kind == "blob", "Symlink/submodule/non-regular tracked path: " + path)
        result[path] = (mode, git(repo, "cat-file", "blob", object_id, env=env).stdout)
    return result


def root_tree(repo, ref, env=None):
    result = read_tree(repo, ref, *ROOT_PATHS, env=env)
    for path in result:
        parts = PurePosixPath(path).parts
        require((len(parts) == 1 and path not in ROOT_DIRECTORIES)
                or (len(parts) > 1 and parts[0] in ROOT_DIRECTORIES),
                "Invalid managed root file/directory shape: " + path)
    return result


def valid_skill_name(name):
    return name in COMPATIBLE_SKILL_NAMES or bool(NAME.fullmatch(name))


def skill_tree(repo, ref):
    result = {}
    for path, value in read_tree(repo, ref, "skills").items():
        parts = PurePosixPath(path).parts
        require(len(parts) >= 3 and valid_skill_name(parts[1]), "Invalid tracked skill name: " + path)
        result[path[len("skills/"):]] = value
    return result


def scan_error(error):
    raise error


def selected_sources(local, requested):
    names = sorted(set(requested or [p.name for p in local.iterdir()
                                    if p.name.startswith("ljg-") or p.name in COMPATIBLE_SKILL_NAMES]))
    for name in names:
        require(valid_skill_name(name), "Invalid skill name: " + repr(name))
        root = local / name
        require(not root.is_symlink() and root.is_dir() and root.resolve().parent == local,
                "Skill directory must stay inside --local without symlinks: " + name)
    tree = {}
    for name in names:
        root = local / name
        for parent, dirs, files in os.walk(root, followlinks=False, onerror=scan_error):
            # Even excluded symlinks are rejected: do not rely on copy-tool link semantics.
            for entry in dirs + files:
                require(not (Path(parent) / entry).is_symlink(), "Symlink in skill source: " + str(Path(parent) / entry))
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
            for filename in sorted(files):
                if filename in EXCLUDED or filename.endswith((".pyc", ".log")):
                    continue
                path = Path(parent) / filename
                relative = path.relative_to(local).as_posix()
                safe_tree_path(relative)
                info = path.stat()
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Non-regular/hard-linked source file: " + relative)
                require(local in path.resolve().parents, "Source path escaped --local: " + relative)
                tree[relative] = ("100755" if info.st_mode & 0o111 else "100644", path.read_bytes())
        require(name + "/SKILL.md" in tree, "Missing SKILL.md in source: " + name)
    return names, tree


def destination_paths(repo, tree):
    for relative in ["skills", ".claude-plugin", *METADATA, *("skills/" + p for p in tree)]:
        target = repo / relative
        for path in (target, *target.parents):
            if path == repo:
                break
            require(not path.is_symlink(), "Symlink in repository destination: " + str(path))
        require(repo in target.resolve().parents, "Destination escaped repository: " + relative)


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def metadata(tree):
    require(all(p in tree for p in METADATA), "Missing plugin/marketplace JSON")
    plugin, market = (strict_json(tree[p][1]) for p in METADATA)
    require(isinstance(plugin, dict) and isinstance(market, dict), "Metadata must be JSON objects")
    require(isinstance(plugin.get("name"), str) and bool(plugin["name"]), "plugin.name must be a nonempty string")
    entries = market.get("plugins")
    require(isinstance(entries, list), "marketplace.plugins must be an array")
    matches = [p for p in entries if isinstance(p, dict) and p.get("name") == plugin.get("name") and p.get("source") == "./"]
    require(len(matches) == 1, "Exactly one marketplace plugin must match plugin.name and source './'")
    versions = [plugin.get("version"), market.get("version"), matches[0].get("version")]
    require(all(isinstance(v, str) and VERSION.fullmatch(v) for v in versions), "Invalid strict major.minor.patch metadata version")
    require(len(set(versions)) == 1, "Metadata version mismatch (plugin, marketplace, marketplace.plugins)")
    return versions[0], plugin, market, matches[0]


def metadata_without_release_version(tree):
    _, plugin, market, entry = metadata(tree)
    for value in (plugin, market, entry):
        del value["version"]
    return plugin, market


def bumped_metadata(tree):
    version, plugin, market, entry = metadata(tree)
    major, minor, patch = map(int, version.split("."))
    new = f"{major}.{minor}.{patch + 1}"
    plugin["version"] = market["version"] = entry["version"] = new
    updated = {path: (tree[path][0], (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
               for path, value in zip(METADATA, (plugin, market))}
    require(metadata(updated)[0] == new, "Version serialization readback failed")
    return new, updated


def changed(before, after):
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


def managed(skills, meta, roots):
    return {**{"skills/" + p: value for p, value in skills.items()}, **meta, **roots}


def write_file(root, relative, value):
    safe_tree_path(relative)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    mode, data = value
    path.write_bytes(data)
    path.chmod(0o755 if mode == "100755" else 0o644)
    require(path.read_bytes() == data, "Write readback failed: " + relative)


def build_commit(build, env, parent, before, after, message, other_parent=None):
    # This directory is exclusively owned by TemporaryDirectory. Remove the last
    # branch's materialized files before loading the next index (file/dir swaps).
    for path in build.iterdir():
        if path.name != ".git":
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
    # Git index operations only occur in this disposable repository. No glob staging.
    git(build, "read-tree", parent, env=env)
    files = changed(before, after)
    for relative in files:
        path = build / relative
        if relative in after:
            write_file(build, relative, after[relative])
        elif path.exists():
            path.unlink()
    if files:
        # Stage one exact set: batching can remove directory children from the
        # index before their later deletion pathspecs are matched. NUL stdin also
        # avoids argv limits without relaxing literal pathspec handling.
        git(build, "add", "--force", "--all", "--pathspec-from-file=-", "--pathspec-file-nul",
            env=env, data=b"".join(path.encode("utf-8") + b"\0" for path in files))
    staged = git(build, "diff", "--cached", "--name-only", "--no-renames", "-z", parent, env=env).stdout
    require(set(filter(None, staged.decode().split("\0"))) == set(files), "Staged files do not match the exact release list")
    # Read all three actual on-disk version values, not only the planned buffers.
    for relative in METADATA:
        if relative not in files:
            write_file(build, relative, after[relative])
    require(metadata({p: (after[p][0], (build / p).read_bytes()) for p in METADATA})[0] == metadata(after)[0],
            "Written metadata version readback failed")
    tree = text(build, "write-tree", env=env)
    parents = ["-p", parent] + (["-p", other_parent] if other_parent else [])
    commit = text(build, "commit-tree", tree, *parents, "-m", message, env=env)
    # Verify committed blobs/modes as well; clean/smudge filters cannot silently alter a release.
    require(read_tree_with_env(build, commit, env) == after, "Committed managed tree differs from the verified release")
    return commit


def read_tree_with_env(build, commit, env):
    # Use the same isolated environment and exact scope for verification as for
    # planning. Root tools must not silently survive from an older md parent.
    return {**read_tree(build, commit, "skills", *METADATA, env=env),
            **root_tree(build, commit, env=env)}


def authenticated_env(repo, env):
    """Carry only transport credentials, never origin rewrites, hooks or filters."""
    result = dict(env)
    count = int(result["GIT_CONFIG_COUNT"])
    records = git(repo, "config", "--null", "--get-regexp", r"^(credential\.|http\.|core\.(sshcommand|askpass)$)", check=False).stdout
    for record in records.split(b"\0"):
        if record:
            key, value = record.decode("utf-8").split("\n", 1)
            result["GIT_CONFIG_KEY_" + str(count)] = key
            result["GIT_CONFIG_VALUE_" + str(count)] = value
            count += 1
    result["GIT_CONFIG_COUNT"] = str(count)
    for key in ("GIT_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_SSH_VARIANT", "GIT_SSL_CAINFO", "GIT_SSL_CAPATH"):
        if key in os.environ:
            result[key] = os.environ[key]
    return result


def args_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("SKILLS_REPO", str(Path.home() / "code/ljg-skills260812")))
    parser.add_argument("--local", default=os.environ.get("SKILLS_LOCAL", str(Path.home() / ".agents/skills")))
    parser.add_argument("--origin", default=os.environ.get("REPO_URL"), help="exact allowed fetch AND push URL")
    parser.add_argument("--source-branch", default="master")
    parser.add_argument("--md-branch", default="md")
    parser.add_argument("--skill", action="append", help="repeatable explicit skill selection")
    parser.add_argument("--message", default="sync ljg-* skills")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="select all local skills; never force-push or bypass safety")
    parser.add_argument("--skip-readme-check", action="store_true")
    return parser


def publish(args):
    no_redirected_git()
    repo = directory(args.repo, "Repository")
    local = directory(args.local, "Skill source")
    for branch in (args.source_branch, args.md_branch):
        require(not branch.startswith("-"), "Invalid branch name")
        git(repo, "check-ref-format", "refs/heads/" + branch)
    require(args.source_branch != args.md_branch, "Source and Markdown branches must differ")
    clean_repo(repo, args.source_branch)
    origin = origin_url(repo, args.origin)
    source_oid = oid(repo, "refs/heads/" + args.source_branch)
    md_oid = oid(repo, "refs/heads/" + args.md_branch, optional=True) or oid(repo, "refs/remotes/origin/" + args.md_branch, optional=True)
    source_tree = skill_tree(repo, source_oid)
    names, local_tree = selected_sources(local, args.skill)
    destination_paths(repo, {**source_tree, **local_tree})
    source_meta = read_tree(repo, source_oid, *METADATA)
    current_version = metadata(source_meta)[0]
    after_skills = {p: value for p, value in source_tree.items() if p.split("/", 1)[0] not in names}
    after_skills.update(local_tree)
    # Root infrastructure is authoritative only in committed source objects.
    # Never read it from the installed skills or from ignored worktree files.
    source_roots = root_tree(repo, source_oid)
    require("README.md" in source_roots, "README.md is missing; commit documentation before publishing")
    documented = {name for name in re.findall(r"[A-Za-z0-9_-]+", source_roots["README.md"][1].decode("utf-8"))
                  if valid_skill_name(name)}
    missing = sorted(set(p.split("/", 1)[0] for p in after_skills) - documented)
    if missing:
        require(args.skip_readme_check or args.dry_run, "README missing skills: " + ", ".join(missing))
        print("WARNING: README missing skills: " + ", ".join(missing))

    # An md commit records the exact source parent. Validate every managed path
    # against that base before applying source updates. Without a marker, only
    # today's exact source conversion/roots (plus legacy versions) are safe.
    md_tree = skill_tree(repo, md_oid) if md_oid else {}
    md_roots = root_tree(repo, md_oid) if md_oid else {}
    md_meta = read_tree(repo, md_oid, *METADATA) if md_oid else {}
    if md_oid:
        metadata(md_meta)
        message = text(repo, "show", "-s", "--format=%B", md_oid)
        markers = re.findall(r"^LJG-Source: ([0-9a-f]{40,64})$", message, flags=re.MULTILINE)
        require(len(markers) <= 1, "Ambiguous Markdown source marker")
        base = markers[0] if markers else source_oid
        if markers:
            require(base in text(repo, "show", "-s", "--format=%P", md_oid).split(), "Markdown source marker must be a direct parent")
            require(git(repo, "merge-base", "--is-ancestor", base, source_oid, check=False).returncode == 0,
                    "Markdown source is not an ancestor of the selected source branch")
        expected = mdize(skill_tree(repo, base))
        drift = changed(expected, md_tree)
        require(not drift, "Unmanaged Markdown differences; migrate them into the source/converter first: " + ", ".join(drift[:20]))
        root_drift = changed(root_tree(repo, base) if markers else source_roots, md_roots)
        require(not root_drift, "Unmanaged Markdown root differences; preserve and migrate them explicitly before publishing: " + ", ".join(root_drift[:20]))
        if markers:
            require(md_meta == read_tree(repo, base, *METADATA), "Unmanaged Markdown metadata differences")
        else:
            require(metadata_without_release_version(md_meta) == metadata_without_release_version(source_meta)
                    and all(md_meta[p][0] == source_meta[p][0] for p in METADATA),
                    "Unmanaged Markdown metadata differences; only the three release versions may differ during legacy migration")
    generated_md = mdize(after_skills)
    skill_changes = changed(source_tree, after_skills)
    new_version, new_meta = bumped_metadata(source_meta) if skill_changes else (current_version, source_meta)
    source_before = managed(source_tree, source_meta, source_roots)
    source_after = managed(after_skills, new_meta, source_roots)
    md_before = managed(md_tree, md_meta, md_roots) if md_oid else source_before
    md_after = managed(generated_md, new_meta, source_roots)
    md_needs_commit = not md_oid or bool(changed(md_before, md_after))
    print("Origin: " + origin)
    print("Source: " + args.source_branch + " @ " + source_oid)
    print("Markdown: " + args.md_branch + " @ " + (md_oid or "(new branch)"))
    print("Skills: " + (", ".join(names) or "(none)"))
    print("Version: " + current_version + " -> " + new_version)
    for branch, before, after in ((args.source_branch, source_before, source_after), (args.md_branch, md_before, md_after)):
        for path in changed(before, after):
            print("  " + branch + ": " + path)
    if args.dry_run:
        print("DRY RUN: read-only plan; no temp files, index writes, commits, or network. Remote freshness is unverified.")
        return
    if not skill_changes and not md_needs_commit:
        print("Nothing to push.")
        return

    # No implicit fetch/pull/rebase. A stale checkout needs an explicit user update.
    remote = {}
    lines = text(repo, "ls-remote", "--heads", "origin", "refs/heads/" + args.source_branch, "refs/heads/" + args.md_branch)
    for line in lines.splitlines():
        value, ref = line.split("\t")
        require(ref not in remote and re.fullmatch(r"[0-9a-f]{40,64}", value), "Invalid remote ref response")
        remote[ref] = value
    for branch, expected in ((args.source_branch, source_oid), (args.md_branch, md_oid)):
        require(remote.get("refs/heads/" + branch) == expected, "Remote/local ref mismatch for " + branch + "; update explicitly, then retry")

    # A throwaway object store with read-only alternates avoids copying history and
    # never leaves commits or changes in the user's repository (even after failure).
    with tempfile.TemporaryDirectory(prefix="ljg-publish-") as temp:
        build = Path(temp) / "build"
        build.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "3", "GIT_CONFIG_KEY_0": "core.hooksPath",
                    "GIT_CONFIG_VALUE_0": os.devnull, "GIT_CONFIG_KEY_1": "init.templateDir", "GIT_CONFIG_VALUE_1": "",
                    "GIT_CONFIG_KEY_2": "core.autocrlf", "GIT_CONFIG_VALUE_2": "false"})
        for role in ("AUTHOR", "COMMITTER"):
            # Read identity using the input repo, but do not copy its hooks/filters/config.
            identity = text(repo, "var", "GIT_" + role + "_IDENT")
            match = re.fullmatch(r"(.*) <([^<>]+)> (\d+) ([+-]\d{4})", identity)
            require(match, "Git identity is not configured")
            env.update({"GIT_" + role + "_NAME": match[1], "GIT_" + role + "_EMAIL": match[2], "GIT_" + role + "_DATE": match[3] + " " + match[4]})
        git(build, "init", "-q", env=env)
        common = Path(text(repo, "rev-parse", "--git-common-dir"))
        objects = (repo / common / "objects").resolve()
        require(objects.is_dir() and "\n" not in str(objects), "Invalid Git object directory")
        (build / ".git/objects/info/alternates").write_text(str(objects) + "\n")
        source_new = build_commit(build, env, source_oid, source_before, source_after,
                                  args.message + " (v" + new_version + ")") if skill_changes else source_oid
        md_new = build_commit(build, env, md_oid or source_new, md_before if md_oid else source_after, md_after,
                              args.message + " [md] (v" + new_version + ")\n\nLJG-Source: " + source_new,
                              other_parent=source_new if md_oid and md_oid != source_new else None) if md_needs_commit else md_oid
        # Detect edits, source changes or target changes that occurred while building.
        clean_repo(repo, args.source_branch)
        require(oid(repo, "refs/heads/" + args.source_branch) == source_oid, "Source branch moved while building")
        require(origin_url(repo, args.origin) == origin, "origin changed while building")
        require(selected_sources(local, args.skill) == (names, local_tree), "Skill source changed while building")
        git(build, "remote", "add", "origin", origin, env=env)
        refspecs = [source_new + ":refs/heads/" + args.source_branch, md_new + ":refs/heads/" + args.md_branch]
        # Atomic push has no non-atomic fallback. Exact leases prevent races; both
        # commits are descendants of the checked remote parents, never history resets.
        leases = ["--force-with-lease=refs/heads/" + branch + ":" + (expected or "")
                  for branch, expected in ((args.source_branch, source_oid), (args.md_branch, md_oid))]
        git(build, "-c", "push.followTags=false", "push", "--atomic", "--no-verify", *leases, "origin", *refspecs,
            env=authenticated_env(repo, env))
        print("Published atomically: " + args.source_branch + "=" + source_new + ", " + args.md_branch + "=" + md_new + "; version " + new_version)
        print("Input repository unchanged. Explicitly fetch/fast-forward it before the next publish; no tag was created.")


def main():
    try:
        publish(args_parser().parse_args())
    except (Refusal, ValueError, OSError, subprocess.SubprocessError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
