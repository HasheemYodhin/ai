import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

/**
 * Manages inline diff views for agent file edits.
 * Opens VS Code's native side-by-side diff editor so the user
 * can review proposed changes before they are applied.
 */
export class DiffManager {
  private _tmpDir: string;

  constructor() {
    this._tmpDir = path.join(os.tmpdir(), 'dabba-diffs');
    if (!fs.existsSync(this._tmpDir)) {
      fs.mkdirSync(this._tmpDir, { recursive: true });
    }
  }

  async showDiff(filePath: string, proposedContent: string, label = 'dabba proposed change'): Promise<boolean> {
    let originalContent = '';
    if (fs.existsSync(filePath)) {
      originalContent = fs.readFileSync(filePath, 'utf-8');
    }
    if (originalContent === proposedContent) { return true; }

    const basename = path.basename(filePath);
    const id = Date.now().toString();
    const tmpFile = path.join(this._tmpDir, `${id}_${basename}`);
    fs.writeFileSync(tmpFile, proposedContent, 'utf-8');

    const originalUri = vscode.Uri.file(filePath);
    const proposedUri = vscode.Uri.file(tmpFile);

    try {
      await vscode.commands.executeCommand('vscode.diff', originalUri, proposedUri, `${basename}: ${label}`, { preview: true });
    } catch {
      await vscode.window.showTextDocument(proposedUri);
    }

    const choice = await vscode.window.showInformationMessage(
      `dabba wants to edit: ${basename}`, { modal: false }, 'Accept', 'Reject'
    );

    try { fs.unlinkSync(tmpFile); } catch { /* ok */ }
    await Promise.resolve(vscode.commands.executeCommand('workbench.action.revertAndCloseActiveEditor')).catch(() => {});

    if (choice === 'Accept') {
      try {
        const dir = path.dirname(filePath);
        if (!fs.existsSync(dir)) { fs.mkdirSync(dir, { recursive: true }); }
        fs.writeFileSync(filePath, proposedContent, 'utf-8');
        return true;
      } catch (err) {
        vscode.window.showErrorMessage(`dabba: failed to write file: ${err}`);
        return false;
      }
    }
    return false;
  }

  /**
   * Show a real before/after diff for an edit the agent already applied.
   * No Accept/Reject — the write already happened; this is purely a live
   * visual record of what changed (VSCode's diff editor colors additions
   * green and deletions red natively, no extra styling needed).
   */
  async showLiveDiff(filePath: string, before: string, after: string): Promise<void> {
    if (before === after) { return; }

    const basename = path.basename(filePath);
    const id = Date.now().toString();
    const beforeFile = path.join(this._tmpDir, `${id}_before_${basename}`);
    fs.writeFileSync(beforeFile, before, 'utf-8');

    const beforeUri = vscode.Uri.file(beforeFile);
    const afterUri = vscode.Uri.file(filePath);

    try {
      await vscode.commands.executeCommand(
        'vscode.diff', beforeUri, afterUri, `${basename} — dabba's edit`, { preview: true },
      );
    } catch {
      // Diff view unavailable for some reason — not critical, skip silently.
    } finally {
      setTimeout(() => { try { fs.unlinkSync(beforeFile); } catch { /* ok */ } }, 60_000);
    }
  }

  /**
   * Show every file changed in one agent turn as a single multi-file diff
   * view — VS Code's native "Changes" multi-diff editor (the same UI Git's
   * Source Control view uses), instead of popping open one diff tab per
   * edited file. Falls back to sequential single-file diffs (showLiveDiff)
   * if the vscode.changes command isn't available on the user's VS Code
   * version (it landed after this extension's minimum engines.vscode).
   */
  async showBatchDiff(edits: Array<{ filePath: string; before: string; after: string }>): Promise<void> {
    const changed = edits.filter((e) => e.before !== e.after);
    if (changed.length === 0) { return; }

    if (changed.length === 1) {
      await this.showLiveDiff(changed[0].filePath, changed[0].before, changed[0].after);
      return;
    }

    const tmpFiles: string[] = [];
    try {
      const resources: [vscode.Uri, vscode.Uri, vscode.Uri][] = changed.map((e) => {
        const basename = path.basename(e.filePath);
        const id = Date.now().toString() + Math.random().toString(36).slice(2);
        const beforeFile = path.join(this._tmpDir, `${id}_before_${basename}`);
        fs.writeFileSync(beforeFile, e.before, 'utf-8');
        tmpFiles.push(beforeFile);
        return [vscode.Uri.file(e.filePath), vscode.Uri.file(beforeFile), vscode.Uri.file(e.filePath)];
      });
      await vscode.commands.executeCommand('vscode.changes', `dabba: ${changed.length} files changed`, resources);
    } catch {
      // vscode.changes unavailable — degrade to one diff tab per file rather
      // than silently showing nothing.
      for (const e of changed) {
        await this.showLiveDiff(e.filePath, e.before, e.after);
      }
    } finally {
      setTimeout(() => {
        for (const f of tmpFiles) { try { fs.unlinkSync(f); } catch { /* ok */ } }
      }, 60_000);
    }
  }

  applyEdit(filePath: string, content: string): boolean {
    try {
      const dir = path.dirname(filePath);
      if (!fs.existsSync(dir)) { fs.mkdirSync(dir, { recursive: true }); }
      fs.writeFileSync(filePath, content, 'utf-8');
      return true;
    } catch { return false; }
  }

  dispose(): void {
    try {
      if (fs.existsSync(this._tmpDir)) {
        fs.readdirSync(this._tmpDir).forEach(f => {
          try { fs.unlinkSync(path.join(this._tmpDir, f)); } catch { /* ok */ }
        });
      }
    } catch { /* ok */ }
  }
}
