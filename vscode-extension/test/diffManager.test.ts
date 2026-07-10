import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { commands, window } from './mocks/vscode';
import { DiffManager } from '../src/diffManager';

describe('DiffManager', () => {
  let tmpFile: string;
  let diffManager: DiffManager;

  beforeEach(() => {
    tmpFile = path.join(os.tmpdir(), `dabba-diffmanager-test-${Date.now()}.txt`);
    diffManager = new DiffManager();
    commands.executeCommand = vi.fn(async () => undefined) as typeof commands.executeCommand;
  });

  afterEach(() => {
    try { fs.unlinkSync(tmpFile); } catch { /* ok */ }
  });

  describe('showDiff', () => {
    it('returns true immediately with no dialog when content is unchanged', async () => {
      fs.writeFileSync(tmpFile, 'same content', 'utf-8');
      window.showInformationMessage = vi.fn(async () => 'Accept') as typeof window.showInformationMessage;

      const result = await diffManager.showDiff(tmpFile, 'same content');
      expect(result).toBe(true);
      expect(window.showInformationMessage).not.toHaveBeenCalled();
    });

    it('writes the proposed content and returns true on Accept', async () => {
      fs.writeFileSync(tmpFile, 'old', 'utf-8');
      window.showInformationMessage = vi.fn(async () => 'Accept') as typeof window.showInformationMessage;

      const result = await diffManager.showDiff(tmpFile, 'new content');
      expect(result).toBe(true);
      expect(fs.readFileSync(tmpFile, 'utf-8')).toBe('new content');
    });

    it('leaves the file untouched and returns false on Reject', async () => {
      fs.writeFileSync(tmpFile, 'old', 'utf-8');
      window.showInformationMessage = vi.fn(async () => 'Reject') as typeof window.showInformationMessage;

      const result = await diffManager.showDiff(tmpFile, 'new content');
      expect(result).toBe(false);
      expect(fs.readFileSync(tmpFile, 'utf-8')).toBe('old');
    });
  });

  describe('showBatchDiff', () => {
    it('does nothing when no file actually changed', async () => {
      await diffManager.showBatchDiff([{ filePath: tmpFile, before: 'x', after: 'x' }]);
      expect(commands.executeCommand).not.toHaveBeenCalled();
    });

    it('falls back to a single live diff (vscode.diff) for exactly one changed file', async () => {
      fs.writeFileSync(tmpFile, 'after', 'utf-8');
      await diffManager.showBatchDiff([{ filePath: tmpFile, before: 'before', after: 'after' }]);
      expect(commands.executeCommand).toHaveBeenCalledWith(
        'vscode.diff', expect.anything(), expect.anything(), expect.stringContaining("dabba's edit"), expect.anything(),
      );
    });

    it('uses the multi-file vscode.changes command for 2+ changed files', async () => {
      const tmpFile2 = tmpFile + '.2';
      fs.writeFileSync(tmpFile, 'after1', 'utf-8');
      fs.writeFileSync(tmpFile2, 'after2', 'utf-8');
      try {
        await diffManager.showBatchDiff([
          { filePath: tmpFile, before: 'before1', after: 'after1' },
          { filePath: tmpFile2, before: 'before2', after: 'after2' },
        ]);
        expect(commands.executeCommand).toHaveBeenCalledWith(
          'vscode.changes', expect.stringContaining('2 files changed'), expect.any(Array),
        );
      } finally {
        try { fs.unlinkSync(tmpFile2); } catch { /* ok */ }
      }
    });

    it('degrades to sequential single-file diffs when vscode.changes is unavailable', async () => {
      const tmpFile2 = tmpFile + '.2';
      fs.writeFileSync(tmpFile, 'after1', 'utf-8');
      fs.writeFileSync(tmpFile2, 'after2', 'utf-8');
      commands.executeCommand = vi.fn(async (command: string) => {
        if (command === 'vscode.changes') { throw new Error('command not found'); }
        return undefined;
      }) as typeof commands.executeCommand;

      try {
        await diffManager.showBatchDiff([
          { filePath: tmpFile, before: 'before1', after: 'after1' },
          { filePath: tmpFile2, before: 'before2', after: 'after2' },
        ]);
        const calls = (commands.executeCommand as ReturnType<typeof vi.fn>).mock.calls;
        expect(calls.some((c: unknown[]) => c[0] === 'vscode.changes')).toBe(true);
        expect(calls.filter((c: unknown[]) => c[0] === 'vscode.diff').length).toBe(2);
      } finally {
        try { fs.unlinkSync(tmpFile2); } catch { /* ok */ }
      }
    });
  });
});
