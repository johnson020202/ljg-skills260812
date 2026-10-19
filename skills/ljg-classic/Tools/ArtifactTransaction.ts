import { lstat, mkdir, mkdtemp, readdir, realpath, rename, rm, rmdir, stat } from "node:fs/promises";
import { basename, dirname, extname, isAbsolute, join, relative, resolve } from "node:path";

export const GENERATED_SLICE_NAME = /^\d+--y-\d+\.png$/;

export interface ArtifactPaths {
  input: string;
  hero?: string;
  html: string;
  png: string;
  manifest: string;
  slices?: string;
}

async function maybeLstat(path: string) {
  try { return await lstat(path); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return null; throw error; }
}

// Resolve existing ancestors too: realpath alone cannot handle a new output file.
async function canonicalPath(path: string): Promise<string> {
  const info = await maybeLstat(path);
  if (info) {
    try { return await realpath(path); }
    catch (error) {
      if (info.isSymbolicLink()) throw new Error(`Unsafe symlink path: ${path}`, { cause: error });
      throw error;
    }
  }
  const parent = dirname(path);
  if (parent === path) throw new Error(`Cannot resolve path: ${path}`);
  return join(await canonicalPath(parent), basename(path));
}

function contains(parent: string, child: string): boolean {
  // Missing leaves have no realpath/inode yet. Conservatively reject case and
  // Unicode-normalization aliases even on case-sensitive volumes.
  const suffix = relative(parent.normalize("NFC").toLowerCase(), child.normalize("NFC").toLowerCase());
  return suffix === "" || (!suffix.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) && suffix !== ".." && !isAbsolute(suffix));
}

async function identity(label: string, path: string, writable: boolean, directory = false) {
  path = resolve(path);
  const link = await maybeLstat(path);
  // Replacing a file symlink silently changes its meaning; never follow it for writes.
  if (writable && !directory && link?.isSymbolicLink()) throw new Error(`Unsafe output symlink: ${label} (${path})`);
  const canonical = await canonicalPath(path);
  const info = link ? await stat(path) : null;
  if (info && (directory ? !info.isDirectory() : !info.isFile())) {
    throw new Error(`Path conflict: ${label} must be a ${directory ? "directory" : "regular file"}: ${path}`);
  }
  return {
    label, path, canonical, writable, directory,
    inode: info ? `${info.dev}:${info.ino}` : null,
    // Directory mtimes can change as staging directories are created beside outputs.
    version: info && !directory ? `${info.size}:${info.mtimeMs}:${info.ctimeMs}` : null,
  };
}

/** Read-only preflight. Its fingerprint is checked again before publishing. */
export async function preflightArtifacts(paths: ArtifactPaths): Promise<string> {
  const roles = [
    await identity("input", paths.input, false),
    ...(paths.hero ? [await identity("hero", paths.hero, false)] : []),
    await identity("HTML", paths.html, true),
    await identity("PNG", paths.png, true),
    await identity("manifest", paths.manifest, true),
    ...(paths.slices ? [await identity("slices", paths.slices, true, true)] : []),
  ];
  for (let left = 0; left < roles.length; left += 1) {
    for (const right of roles.slice(left + 1)) {
      const first = roles[left];
      if (contains(first.canonical, right.canonical) || contains(right.canonical, first.canonical)
        || (first.inode !== null && first.inode === right.inode)) {
        throw new Error(`Path conflict/alias: ${first.label} (${first.path}) overlaps ${right.label} (${right.path})`);
      }
    }
  }
  const generated = [];
  if (paths.slices && (await maybeLstat(paths.slices))) {
    for (const entry of (await readdir(paths.slices, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      if (!GENERATED_SLICE_NAME.test(entry.name)) {
        if (GENERATED_SLICE_NAME.test(entry.name.normalize("NFC").toLowerCase())) {
          throw new Error(`Path conflict/alias: unmanaged QA entry resembles a generated slice: ${entry.name}`);
        }
        continue;
      }
      const slice = await identity("generated slice", join(paths.slices, entry.name), true);
      if (roles.some(role => role.inode !== null && role.inode === slice.inode)) {
        throw new Error(`Path conflict/alias: generated slice ${slice.path}`);
      }
      generated.push(slice);
    }
  }
  return JSON.stringify({ roles, generated });
}

interface PendingArtifact {
  target: string;
  staged?: string;
  backup: string;
  backedUp: boolean;
  installed: boolean;
}

type Rename = typeof rename;

/** Sibling staging (same filesystem), then reversible per-file renames.
 * Unrelated files in a QA directory are never copied, removed, or followed.
 */
export class ArtifactTransaction {
  private roots = new Map<string, string>();
  private entries = new Map<string, PendingArtifact>();
  private createdDirectories: string[] = [];
  private retainBackups = false;

  private async rootFor(target: string): Promise<string> {
    let parent = dirname(resolve(target));
    while (!(await maybeLstat(parent))) parent = dirname(parent);
    const canonical = await realpath(parent);
    let root = this.roots.get(canonical);
    if (!root) {
      root = await mkdtemp(join(canonical, ".classic-stage-"));
      this.roots.set(canonical, root);
    }
    return root;
  }

  async stageFile(target: string): Promise<string> {
    const root = await this.rootFor(target);
    const staged = join(root, `new-${this.entries.size}${extname(target)}`);
    await this.adopt(target, staged);
    return staged;
  }

  async scratchDirectory(target: string): Promise<string> {
    return mkdtemp(join(await this.rootFor(join(target, ".slice")), "slices-"));
  }

  async adopt(target: string, staged?: string): Promise<void> {
    target = resolve(target);
    if (this.entries.has(target)) throw new Error(`Duplicate transaction target: ${target}`);
    const root = await this.rootFor(target);
    this.entries.set(target, {
      target, staged, backup: join(root, `old-${this.entries.size}`), backedUp: false, installed: false,
    });
  }

  private async ensureDirectory(path: string): Promise<void> {
    if (await maybeLstat(path)) return;
    await this.ensureDirectory(dirname(path));
    await mkdir(path);
    this.createdDirectories.push(path);
  }

  async commit(renameFile: Rename = rename): Promise<void> {
    try {
      for (const entry of this.entries.values()) {
        await this.ensureDirectory(dirname(entry.target));
        if (await maybeLstat(entry.target)) {
          await renameFile(entry.target, entry.backup);
          entry.backedUp = true;
        }
        if (entry.staged) {
          await renameFile(entry.staged, entry.target);
          entry.installed = true;
        }
      }
    } catch (error) {
      const failures: string[] = [];
      for (const entry of [...this.entries.values()].reverse()) {
        try {
          if (entry.installed) await rm(entry.target);
          // Use the real rename for recovery, not the injected test fault.
          if (entry.backedUp) await rename(entry.backup, entry.target);
        } catch (rollbackError) { failures.push(`${entry.target}: ${String(rollbackError)}`); }
      }
      if (failures.length) {
        this.retainBackups = true;
        throw new Error(`Artifact rollback incomplete; keep recovery files in ${[...this.roots.values()].join(", ")}: ${failures.join("; ")}`, { cause: error });
      }
      throw error;
    }
  }

  async dispose(): Promise<void> {
    if (this.retainBackups) return;
    for (const root of this.roots.values()) await rm(root, { recursive: true, force: true });
    // Only remove directories created by this transaction, and only if still empty.
    for (const path of [...this.createdDirectories].reverse()) {
      try { await rmdir(path); }
      catch (error) {
        if (!["ENOENT", "ENOTEMPTY", "EEXIST"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error;
      }
    }
  }
}
