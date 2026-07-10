import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { workspace, window, Uri } from './mocks/vscode';
import { ChatViewProvider, isDangerousTool } from '../src/chatViewProvider';

type AnyMessage = Record<string, unknown>;

function makeContext() {
  const workspaceState = new Map<string, unknown>();
  return {
    extensionUri: Uri.file('/ext'),
    workspaceState: {
      get: vi.fn((key: string) => workspaceState.get(key)),
      update: vi.fn((key: string, value: unknown) => { workspaceState.set(key, value); }),
    },
    globalState: { get: vi.fn(), update: vi.fn() },
    secrets: { get: vi.fn(async () => undefined), store: vi.fn(async () => {}), delete: vi.fn(async () => {}) },
  } as unknown as import('vscode').ExtensionContext;
}

function makeSettings() {
  return {
    getSettings: vi.fn(() => ({
      apiEndpoint: 'http://localhost:8080',
      model: 'dabba',
      effort: 'medium',
      maxTokens: 4096,
      temperature: 0.7,
      autoReviewOnSave: false,
      enableDiagnostics: true,
      theme: 'auto' as const,
    })),
    getApiKey: vi.fn(async () => undefined),
    setApiKey: vi.fn(async () => {}),
    clearApiKey: vi.fn(async () => {}),
    onDidChangeSettings: vi.fn(() => ({ dispose: () => {} })),
    dispose: vi.fn(),
  } as unknown as import('../src/settings').SettingsManager;
}

/** Registers the real onDidReceiveMessage handler via resolveWebviewView and returns a way to drive it. */
function attachWebview(provider: ChatViewProvider) {
  const posted: AnyMessage[] = [];
  let handler: ((message: AnyMessage) => Promise<void> | void) | undefined;

  const webview = {
    options: {},
    html: '',
    cspSource: 'test-csp',
    asWebviewUri: (uri: Uri) => uri,
    postMessage: vi.fn((msg: AnyMessage) => { posted.push(msg); return Promise.resolve(true); }),
    onDidReceiveMessage: (cb: (message: AnyMessage) => Promise<void> | void) => { handler = cb; return { dispose: () => {} }; },
  };

  provider.resolveWebviewView(
    { webview } as unknown as import('vscode').WebviewView,
    {} as import('vscode').WebviewViewResolveContext,
    {} as import('vscode').CancellationToken,
  );

  return {
    posted,
    send: async (message: AnyMessage) => { await handler?.(message); },
  };
}

describe('ChatViewProvider', () => {
  beforeEach(() => {
    workspace.workspaceFolders = undefined;
    workspace.isTrusted = true;
    window.activeTextEditor = undefined;
  });

  it('clearConversation aborts, clears changed files, and posts clearMessages', async () => {
    const provider = new ChatViewProvider(Uri.file('/ext'), makeSettings(), makeContext());
    const { posted } = attachWebview(provider);

    (provider as unknown as { _changedFiles: Set<string> })._changedFiles.add('foo.ts');
    await provider.clearConversation();

    expect((provider as unknown as { _changedFiles: Set<string> })._changedFiles.size).toBe(0);
    expect(posted.some((m) => m.type === 'clearMessages')).toBe(true);
  });

  it('clearConversation is reachable through the real message-handler switch (case "clearConversation")', async () => {
    const provider = new ChatViewProvider(Uri.file('/ext'), makeSettings(), makeContext());
    const { posted, send } = attachWebview(provider);

    await send({ type: 'clearConversation' });
    expect(posted.some((m) => m.type === 'clearMessages')).toBe(true);
  });

  it('pinFile/unpinFile persist to the active session and notify the webview', async () => {
    const provider = new ChatViewProvider(Uri.file('/ext'), makeSettings(), makeContext());
    const { posted, send } = attachWebview(provider);

    await send({ type: 'pinFile', relativePath: 'src/foo.ts' });
    let changed = posted.filter((m) => m.type === 'pinnedFilesChanged').pop();
    expect(changed?.pinnedFiles).toEqual(['src/foo.ts']);

    await send({ type: 'pinFile', relativePath: 'src/foo.ts' }); // re-pinning the same file is a no-op, not a duplicate
    changed = posted.filter((m) => m.type === 'pinnedFilesChanged').pop();
    expect(changed?.pinnedFiles).toEqual(['src/foo.ts']);

    await send({ type: 'unpinFile', relativePath: 'src/foo.ts' });
    changed = posted.filter((m) => m.type === 'pinnedFilesChanged').pop();
    expect(changed?.pinnedFiles).toEqual([]);
  });

  it('regenerateLastResponse truncates the transcript after the last user message', async () => {
    const provider = new ChatViewProvider(Uri.file('/ext'), makeSettings(), makeContext());
    attachWebview(provider);

    const session = (provider as unknown as { _sessions: Array<{ id: string; messages: AnyMessage[] }> })._sessions[0];
    session.messages = [
      { type: 'addMessage', role: 'user', content: 'first' },
      { type: 'agentText', content: 'reply 1' },
      { type: 'addMessage', role: 'user', content: 'second' },
      { type: 'agentText', content: 'reply 2' },
      { type: 'toolCall', name: 'shell_exec' },
    ];

    (provider as unknown as { _truncateAfterLastUserMessage: () => void })._truncateAfterLastUserMessage();

    expect(session.messages).toEqual([
      { type: 'addMessage', role: 'user', content: 'first' },
      { type: 'agentText', content: 'reply 1' },
    ]);
  });

  describe('_primaryWorkspaceFolder', () => {
    it('returns undefined with no workspace folders open', () => {
      const provider = new ChatViewProvider(Uri.file('/ext'), makeSettings(), makeContext());
      expect((provider as unknown as { _primaryWorkspaceFolder: () => unknown })._primaryWorkspaceFolder()).toBeUndefined();
    });

    it('falls back to the first folder when there is no active editor', () => {
      workspace.workspaceFolders = [
        { uri: Uri.file('/repo-a'), name: 'a', index: 0 },
        { uri: Uri.file('/repo-b'), name: 'b', index: 1 },
      ];
      const provider = new ChatViewProvider(Uri.file('/ext'), makeSettings(), makeContext());
      const primary = (provider as unknown as { _primaryWorkspaceFolder: () => { uri: Uri } })._primaryWorkspaceFolder();
      expect(primary?.uri.fsPath).toBe('/repo-a');
    });

    it('prefers the folder containing the active editor over folders[0]', () => {
      workspace.workspaceFolders = [
        { uri: Uri.file('/repo-a'), name: 'a', index: 0 },
        { uri: Uri.file('/repo-b'), name: 'b', index: 1 },
      ];
      window.activeTextEditor = { document: { uri: Uri.file('/repo-b/src/x.ts') } } as unknown;
      workspace.getWorkspaceFolder = vi.fn(() => ({ uri: Uri.file('/repo-b'), name: 'b', index: 1 })) as typeof workspace.getWorkspaceFolder;

      const provider = new ChatViewProvider(Uri.file('/ext'), makeSettings(), makeContext());
      const primary = (provider as unknown as { _primaryWorkspaceFolder: () => { uri: Uri } })._primaryWorkspaceFolder();
      expect(primary?.uri.fsPath).toBe('/repo-b');
    });
  });

  describe('dispose', () => {
    it('aborts any in-flight request and denies every pending tool approval', async () => {
      const provider = new ChatViewProvider(Uri.file('/ext'), makeSettings(), makeContext());
      attachWebview(provider);

      const abort = { abort: vi.fn(), signal: {} };
      (provider as unknown as { _abort: unknown })._abort = abort;
      (provider as unknown as { _pendingApprovalCallIds: Set<string> })._pendingApprovalCallIds.add('call-1');
      (provider as unknown as { _pendingApprovalCallIds: Set<string> })._pendingApprovalCallIds.add('call-2');

      const fetchSpy = vi.fn(async () => ({ ok: true })) as unknown as typeof fetch;
      vi.stubGlobal('fetch', fetchSpy);

      await provider.dispose();

      expect(abort.abort).toHaveBeenCalledOnce();
      expect(fetchSpy).toHaveBeenCalledTimes(2);
      expect((provider as unknown as { _pendingApprovalCallIds: Set<string> })._pendingApprovalCallIds.size).toBe(0);

      vi.unstubAllGlobals();
    });
  });

  describe('artifact tools (markdown_to_pdf/markdown_to_docx)', () => {
    it('surfaces the generated file with isArtifact + filePath, and adds it to changedFiles', async () => {
      const provider = new ChatViewProvider(Uri.file('/ext'), makeSettings(), makeContext());
      const { posted } = attachWebview(provider);

      await (provider as unknown as {
        _handleAgentEvent: (event: { type: string; content: unknown }, startTime: number) => Promise<void>;
      })._handleAgentEvent(
        {
          type: 'tool_result',
          content: {
            tool: 'markdown_to_pdf',
            call_id: 'call-pdf-1',
            success: true,
            output: JSON.stringify({ status: 'success', path: '/repo/report.pdf', size: 1234, exists: true }),
          },
        },
        Date.now(),
      );

      const toolResult = posted.find((m) => m.type === 'toolResult');
      expect(toolResult?.isArtifact).toBe(true);
      expect(toolResult?.filePath).toBe('/repo/report.pdf');
      expect(toolResult?.isEdit).toBe(false); // must NOT be treated as a text-diffable edit

      const fileChanged = posted.find((m) => m.type === 'fileChanged');
      expect(fileChanged?.filePath).toBe('/repo/report.pdf');

      expect((provider as unknown as { _changedFiles: Set<string> })._changedFiles.has('/repo/report.pdf')).toBe(true);
    });

    it('does not claim an artifact path when the tool failed', async () => {
      const provider = new ChatViewProvider(Uri.file('/ext'), makeSettings(), makeContext());
      const { posted } = attachWebview(provider);

      await (provider as unknown as {
        _handleAgentEvent: (event: { type: string; content: unknown }, startTime: number) => Promise<void>;
      })._handleAgentEvent(
        {
          type: 'tool_result',
          content: { tool: 'markdown_to_docx', call_id: 'call-docx-1', success: false, error: 'disk full' },
        },
        Date.now(),
      );

      const toolResult = posted.find((m) => m.type === 'toolResult');
      expect(toolResult?.isArtifact).toBe(false);
      expect(posted.some((m) => m.type === 'fileChanged')).toBe(false);
    });
  });

  describe('isDangerousTool', () => {
    it('flags known dangerous tools and any mcp__-prefixed tool', () => {
      expect(isDangerousTool('shell_exec')).toBe(true);
      expect(isDangerousTool('file_write')).toBe(true);
      expect(isDangerousTool('mcp__filesystem__write_file')).toBe(true);
      expect(isDangerousTool('file_read')).toBe(false);
      expect(isDangerousTool('web_search')).toBe(false);
    });
  });
});
