import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { spawn, ChildProcessWithoutNullStreams } from 'child_process';
import { SettingsManager } from './settings';
import { DiffManager } from './diffManager';

interface Session {
  id: string;
  label: string;
  messages: Record<string, unknown>[];
  createdAt?: number; // epoch ms; absent on sessions persisted before this field existed
  pinnedFiles?: string[]; // relative paths, auto-included in every message this session — absent on sessions persisted before this field existed
}

// Must match the real tool names registered in dabba/tools/*.py — these
// previously listed made-up names (run_command, write_file, etc.) that never
// matched any actual tool, so the permission gate and auto-diff never fired.
const DANGEROUS_TOOLS = new Set(['shell_exec', 'file_write', 'file_edit', 'markdown_to_pdf', 'markdown_to_docx']);
const EDIT_TOOLS = new Set(['file_write', 'file_edit']);

// Tools that produce a real binary file (dabba/tools/artifact_tools.py) —
// deliberately NOT in EDIT_TOOLS, since a text diff on PDF/DOCX bytes would
// be garbage, but that also meant nothing ever tracked the output path or
// offered a way to open it: the tool card just showed "Created (N bytes)"
// with no button, and the user had to dig the path out of the raw JSON.
const ARTIFACT_TOOLS = new Set(['markdown_to_pdf', 'markdown_to_docx']);

// Extensions VS Code's own openTextDocument/showTextDocument would render
// as garbled binary-as-text — these need the OS's own viewer instead.
const BINARY_EXTENSIONS = new Set(['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt']);

// Every "mcp__<server>__<tool>" tool is arbitrary third-party code from a
// user-configured external MCP server (dabba/agent/mcp_client.py) — always
// dangerous regardless of the static set above, same rule as the server's
// _requires_approval() in dabba/api/agent_endpoints.py.
export function isDangerousTool(toolName: string): boolean {
  return DANGEROUS_TOOLS.has(toolName) || toolName.startsWith('mcp__');
}

// Event types worth saving to disk and replaying on reload / session switch.
// Everything else (spinners, pickers, transient errors) is UI-only.
const PERSISTABLE_EVENTS = new Set([
  'addMessage', 'agentText', 'toolCall', 'toolResult', 'todoUpdate', 'agentPlan', 'fileChanged',
]);

const SESSIONS_STORAGE_KEY = 'dabba.chatSessions.v1';
const MAX_STORED_MESSAGES_PER_SESSION = 500;

export class ChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'dabba.chat';
  private _view?: vscode.WebviewView;
  private _abort?: AbortController;
  private _diffManager: DiffManager;

  // Session management — persisted to workspaceState so history survives reloads
  private _sessions: Session[] = [{ id: '1', label: 'Session 1', messages: [], createdAt: Date.now() }];
  private _activeSessionId = '1';
  private _sessionCounter = 1;

  // 'ask' shows a permission card before shell_exec/file_write/file_edit; 'auto' skips it
  // Real gate lives server-side (agent_endpoints.py _pending_approvals) —
  // this just tells the server which mode to use per-request.
  private _permissionMode: 'ask' | 'auto' = 'ask';

  // Workspace file list for @-mentions
  private _workspaceFiles: string[] = [];

  // Voice input: recording happens on the extension host via `arecord` (see
  // startVoiceInput) rather than in the webview, since VS Code webviews
  // can't reliably get microphone permission via getUserMedia.
  private _recordingProcess?: ChildProcessWithoutNullStreams;
  private _recordingPath?: string;

  // Files touched by the agent in the current run — shown as a live chip row
  private _changedFiles: Set<string> = new Set();

  // Captures each edit tool's target path + original content the moment its
  // tool_call arrives — before the server has actually executed it — so the
  // diff shown afterward compares real before/after content. Previously the
  // diff compared the file against the tool's plain success-message string,
  // and tool_result never even carried a file_path field, so it never fired.
  private _pendingEdits: Map<string, { filePath: string; before: string }> = new Map();

  // Every file touched during the current turn, keyed by absolute path so a
  // file edited twice in one turn keeps its ORIGINAL before-content and its
  // LATEST after-content — shown as one batched multi-file diff at turn end
  // instead of a diff tab popping open after every single edit.
  private _turnEdits: Map<string, { filePath: string; before: string; after: string }> = new Map();
  private _lastTurnEdits: Array<{ filePath: string; before: string; after: string }> = [];

  // call_ids currently awaiting a user decision server-side (agent_endpoints.py
  // _pending_approvals). Tracked so dispose() can deny them on shutdown instead
  // of leaving the server's async generator paused forever on a dead client.
  private _pendingApprovalCallIds: Set<string> = new Set();

  // Last user turn sent to /v1/agent, kept so a failed request can be retried
  // (via the 'retryLastMessage' webview message) without the webview needing
  // to remember its own composer state.
  private _lastRequest?: {
    text: string;
    attachments: Array<{ name: string; path: string; isImage: boolean; base64Data?: string }>;
    mentions: Array<{ relativePath: string; content: string }>;
  };

  // Why the in-flight request's AbortController was triggered — distinguishes
  // a user-initiated stop / connect timeout / extension shutdown in the catch
  // block, since AbortError alone doesn't say which.
  private _abortReason?: 'user' | 'timeout' | 'shutdown';

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly settings: SettingsManager,
    private readonly context: vscode.ExtensionContext,
  ) {
    this._diffManager = new DiffManager();
    // Fire-and-forget — findFiles resolves shortly after; the constructor
    // itself can't be async, and nothing needs the list synchronously here.
    void this._refreshWorkspaceFiles();
    this._loadPersistedSessions();
  }

  /** Restore saved sessions/messages from workspaceState, or keep the fresh default. */
  private _loadPersistedSessions(): void {
    const saved = this.context.workspaceState.get<{ sessions: Session[]; active: string; counter: number }>(SESSIONS_STORAGE_KEY);
    if (saved && Array.isArray(saved.sessions) && saved.sessions.length > 0) {
      this._sessions = saved.sessions;
      this._activeSessionId = saved.active || saved.sessions[0].id;
      this._sessionCounter = saved.counter || saved.sessions.length;
    }
  }

  private _persistSessions(): void {
    this.context.workspaceState.update(SESSIONS_STORAGE_KEY, {
      sessions: this._sessions,
      active: this._activeSessionId,
      counter: this._sessionCounter,
    });
  }

  /** Record a content-bearing event into the active session's transcript for replay later. */
  private _record(message: Record<string, unknown>): void {
    const session = this._sessions.find((s) => s.id === this._activeSessionId);
    if (!session) { return; }
    session.messages.push(message);
    if (session.messages.length > MAX_STORED_MESSAGES_PER_SESSION) {
      session.messages.splice(0, session.messages.length - MAX_STORED_MESSAGES_PER_SESSION);
    }
    this._persistSessions();
  }

  /**
   * Refreshes the @-mention file list via vscode.workspace.findFiles instead
   * of a manual fs.readdirSync walk — this automatically respects
   * .gitignore/.vscodeignore/files.exclude/search.exclude (the manual walk
   * only skipped a fixed hardcoded set of directory names) and searches
   * every workspace folder in a multi-root workspace, not just the first.
   */
  private async _refreshWorkspaceFiles(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) { this._workspaceFiles = []; return; }

    // findFiles only ever matches files, never directories, so no extra
    // fs.stat filtering is needed here.
    const uris = await vscode.workspace.findFiles('**/*', undefined, 5000);
    const multiRoot = folders.length > 1;
    this._workspaceFiles = uris.map((u) => vscode.workspace.asRelativePath(u, multiRoot));
  }

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): void {
    this._view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };
    webviewView.webview.html = this._getHtmlContent(webviewView.webview);

    webviewView.webview.onDidReceiveMessage(async (message) => {
      switch (message.type) {
        case 'sendMessage':
          await this._runAgent(message.text, message.attachments || [], message.mentions || []);
          break;
        case 'stopAgent':
          this._abortReason = 'user';
          this._abort?.abort();
          break;
        case 'retryLastMessage':
          if (this._lastRequest) {
            await this._runAgent(this._lastRequest.text, this._lastRequest.attachments, this._lastRequest.mentions);
          }
          break;
        case 'regenerateLastResponse':
          if (this._lastRequest && !this._abort) {
            this._truncateAfterLastUserMessage();
            this._postMessage({ type: 'removeLastTurn' });
            await this._runAgent(this._lastRequest.text, this._lastRequest.attachments, this._lastRequest.mentions);
          }
          break;
        case 'clearConversation':
          await this.clearConversation();
          break;
        case 'openSettings':
          await this._sendSettingsToPanel();
          break;
        case 'saveSettings':
          await this._saveSettingsFromPanel(message.settings);
          break;
        case 'saveApiKey':
          await this.settings.setApiKey(message.key);
          this._postMessage({ type: 'apiKeySaved' });
          break;
        case 'openNativeSettings':
          vscode.commands.executeCommand('workbench.action.openSettings', 'dabba');
          break;
        case 'openMcpPanel':
          await this._sendMcpDataToPanel();
          break;
        case 'addMcpServer':
          await this._addMcpServer(message.name, message.command, message.args, message.env);
          break;
        case 'deleteMcpServer':
          await this._deleteMcpServer(message.name);
          break;
        case 'reloadMcpServers':
          await this._reloadMcpServers();
          break;
        case 'insertCode':
          await this._insertCodeAtCursor(message.code);
          break;
        case 'loadModels':
          await this._loadModels();
          break;
        case 'setModel':
          await this._setModel(message.model);
          break;
        case 'setEffort':
          await this._setEffort(message.effort);
          break;
        case 'togglePermissionMode':
          this._permissionMode = this._permissionMode === 'ask' ? 'auto' : 'ask';
          this._postMessage({ type: 'permissionModeChanged', mode: this._permissionMode });
          break;
        case 'ready':
          // The webview just (re)mounted its script — resend session state and
          // replay the active session's transcript. Without this, a fresh
          // webview (e.g. after "Reload Window") never learns about existing
          // sessions at all: it only ever received them via actions like
          // delete/switch, never on initial load.
          this._postMessage({ type: 'sessionsInit', sessions: this._sessions, active: this._activeSessionId });
          this._replaySession(this._activeSessionId);
          await this._sendStartupStatus();
          break;
        case 'attachFile':
          await this._attachFile();
          break;
        case 'startVoiceInput':
          this._startVoiceRecording();
          break;
        case 'stopVoiceInput':
          await this._stopVoiceRecording();
          break;
        case 'searchFiles':
          await this._refreshWorkspaceFiles();
          this._postMessage({ type: 'fileList', files: this._workspaceFiles.slice(0, 200) });
          break;
        case 'getContextPreview':
          this._sendContextPreview();
          break;
        case 'getMentionFileContent':
          await this._resolveMentionFile(message.relativePath);
          break;
        case 'pinFile':
          this._pinFile(message.relativePath);
          break;
        case 'unpinFile':
          this._unpinFile(message.relativePath);
          break;
        case 'approveToolCall':
          await this._sendApproval(message.callId, true);
          break;
        case 'denyToolCall':
          await this._sendApproval(message.callId, false);
          break;
        case 'newSession':
          this._newSession();
          break;
        case 'switchSession':
          this._activeSessionId = message.id;
          this._persistSessions();
          this._postMessage({ type: 'clearMessages', silent: true });
          this._replaySession(message.id);
          break;
        case 'deleteSession':
          await this._deleteSession(message.id);
          break;
        case 'deleteAllHistory':
          await this._deleteAllHistory();
          break;
        case 'viewDiff':
          await this._handleViewDiff(message.filePath, message.content);
          break;
        case 'openFile':
          await this._openFile(message.filePath);
          break;
        case 'viewChangedFiles':
          if (this._lastTurnEdits.length > 0) {
            await this._diffManager.showBatchDiff(this._lastTurnEdits);
          } else if (this._changedFiles.size > 0) {
            await vscode.commands.executeCommand('workbench.view.scm');
          }
          break;
      }
    });

    // Session info + history replay is sent once the webview signals 'ready'
    // (posting before its script attaches a listener would silently drop the message).
  }

  /** Re-emit a session's stored transcript so the webview looks the way it did before reload. */
  private _replaySession(sessionId: string): void {
    const session = this._sessions.find((s) => s.id === sessionId);
    if (session) {
      for (const msg of session.messages) {
        this._view?.webview.postMessage(msg);
      }
    }
    this._view?.webview.postMessage({ type: 'restoreDone' });
  }

  /**
   * Clear the active session — used by the in-panel clear button, the
   * `clearConversation` webview message, and the `dabba.clearConversation`
   * command. Public so the command handler can call this directly instead
   * of the generic `workbench.action.webview.sendMessage`, which only
   * reaches whichever webview currently has focus (not necessarily this
   * one) and silently no-ops otherwise.
   */
  public async clearConversation(): Promise<void> {
    this._abort?.abort();
    this._changedFiles.clear();
    this._clearActiveSessionMessages();
    await this._resetAgent();
    this._postMessage({ type: 'clearMessages' });
  }

  /**
   * Called from deactivate() so nothing is left orphaned server-side when
   * the extension shuts down mid-conversation:
   * - Aborts any in-flight /v1/agent fetch (drops the connection so the
   *   server's async generator sees the client disconnect).
   * - Denies every tool call still awaiting a user decision, so the
   *   server's paused Future (agent_endpoints.py _pending_approvals)
   *   resolves instead of hanging until APPROVAL_TIMEOUT_SECONDS expires.
   * Best-effort — deactivate() has a limited time budget, so approval
   * denials are sent concurrently rather than one at a time.
   */
  public async dispose(): Promise<void> {
    this._abortReason = 'shutdown';
    this._abort?.abort();

    const pending = Array.from(this._pendingApprovalCallIds);
    this._pendingApprovalCallIds.clear();
    await Promise.all(pending.map((callId) => this._sendApproval(callId, false)));
  }

  /** Clear the active session's stored transcript (used by /clear and the clear button). */
  private _clearActiveSessionMessages(): void {
    const session = this._sessions.find((s) => s.id === this._activeSessionId);
    if (session) {
      session.messages = [];
      this._persistSessions();
    }
  }

  private _getActiveSession(): Session | undefined {
    return this._sessions.find((s) => s.id === this._activeSessionId);
  }

  /** Pin a file so its content is auto-included in every message for the rest of this session. */
  private _pinFile(relativePath: string): void {
    const session = this._getActiveSession();
    if (!session) { return; }
    if (!session.pinnedFiles) { session.pinnedFiles = []; }
    if (!session.pinnedFiles.includes(relativePath)) {
      session.pinnedFiles.push(relativePath);
      this._persistSessions();
    }
    this._postMessage({ type: 'pinnedFilesChanged', pinnedFiles: session.pinnedFiles });
  }

  private _unpinFile(relativePath: string): void {
    const session = this._getActiveSession();
    if (!session || !session.pinnedFiles) { return; }
    session.pinnedFiles = session.pinnedFiles.filter((p) => p !== relativePath);
    this._persistSessions();
    this._postMessage({ type: 'pinnedFilesChanged', pinnedFiles: session.pinnedFiles });
  }

  /** Read every pinned file's CURRENT content (not cached) for injection into the next turn. */
  private _readPinnedFiles(): Array<{ relativePath: string; content: string }> {
    const session = this._getActiveSession();
    const primary = this._primaryWorkspaceFolder();
    if (!session?.pinnedFiles?.length || !primary) { return []; }

    const result: Array<{ relativePath: string; content: string }> = [];
    for (const relativePath of session.pinnedFiles) {
      const fullPath = path.isAbsolute(relativePath) ? relativePath : path.join(primary.uri.fsPath, relativePath);
      try {
        result.push({ relativePath, content: fs.readFileSync(fullPath, 'utf-8').slice(0, 8000) });
      } catch {
        result.push({ relativePath, content: '(pinned file could not be read)' });
      }
    }
    return result;
  }

  /**
   * Drops the last user turn and everything the agent did after it from the
   * active session's persisted transcript, so "Regenerate" doesn't leave the
   * old response sitting in history alongside the new one after a reload.
   */
  private _truncateAfterLastUserMessage(): void {
    const session = this._sessions.find((s) => s.id === this._activeSessionId);
    if (!session) { return; }
    for (let i = session.messages.length - 1; i >= 0; i--) {
      const m = session.messages[i];
      if (m.type === 'addMessage' && m.role === 'user') {
        session.messages = session.messages.slice(0, i);
        this._persistSessions();
        return;
      }
    }
  }

  private _newSession(): void {
    this._sessionCounter++;
    const id = String(this._sessionCounter);
    const label = `Session ${this._sessionCounter}`;
    const createdAt = Date.now();
    this._sessions.push({ id, label, messages: [], createdAt });
    this._activeSessionId = id;
    this._changedFiles.clear();
    this._persistSessions();
    this._postMessage({ type: 'sessionCreated', id, label, createdAt });
    this._postMessage({ type: 'clearMessages' });
    this._resetAgent();
  }

  /** Delete one session tab. If it was active, reset the visible chat + agent context. */
  private async _deleteSession(id: string): Promise<void> {
    const idx = this._sessions.findIndex((s) => s.id === id);
    if (idx === -1) { return; }

    const wasActive = this._activeSessionId === id;
    this._sessions.splice(idx, 1);

    if (this._sessions.length === 0) {
      this._sessionCounter++;
      const freshId = String(this._sessionCounter);
      this._sessions.push({ id: freshId, label: `Session ${this._sessionCounter}`, messages: [] });
    }

    if (wasActive) {
      this._activeSessionId = this._sessions[0].id;
      this._abort?.abort();
      await this._resetAgent();
      this._postMessage({ type: 'clearMessages' });
      this._replaySession(this._activeSessionId);
    }

    this._persistSessions();
    this._postMessage({ type: 'sessionsInit', sessions: this._sessions, active: this._activeSessionId });
  }

  /** Wipe every session and start over with a single blank one. */
  private async _deleteAllHistory(): Promise<void> {
    this._abort?.abort();
    this._sessionCounter = 1;
    this._sessions = [{ id: '1', label: 'Session 1', messages: [] }];
    this._activeSessionId = '1';
    this._changedFiles.clear();
    this._persistSessions();
    await this._resetAgent();
    this._postMessage({ type: 'clearMessages' });
    this._postMessage({ type: 'sessionsInit', sessions: this._sessions, active: this._activeSessionId });
    this._postMessage({ type: 'historyDeleted' });
  }

  /** Push current settings + whether an API key is stored into the in-panel Settings screen. */
  private async _sendStartupStatus(): Promise<void> {
    const settings = this.settings.getSettings();
    const hasApiKey = Boolean(await this.settings.getApiKey());
    const workspaceName = vscode.workspace.name || 'No workspace open';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3_000);
    let backendReachable = false;
    try {
      const response = await fetch(`${settings.apiEndpoint}/health`, { signal: controller.signal });
      backendReachable = response.ok;
    } catch {
      backendReachable = false;
    } finally {
      clearTimeout(timer);
    }
    this._postMessage({ type: 'startupStatus', backendReachable, hasApiKey, workspaceName });
  }

  /** Push current settings + whether an API key is stored into the in-panel Settings screen. */
  private async _sendSettingsToPanel(): Promise<void> {
    const settings = this.settings.getSettings();
    const key = await this.settings.getApiKey();
    this._postMessage({
      type: 'settingsData',
      settings,
      hasApiKey: !!key,
      maskedApiKey: key ? `${key.slice(0, 6)}…${key.slice(-4)}` : '',
    });
  }

  /** Persist settings edited in the in-panel Settings screen back to VSCode config. */
  private async _saveSettingsFromPanel(settings: Partial<import('./settings').DabbaSettings>): Promise<void> {
    const config = vscode.workspace.getConfiguration('dabba');
    const targets: Array<keyof import('./settings').DabbaSettings> = [
      'apiEndpoint', 'model', 'effort', 'maxTokens', 'temperature',
      'autoReviewOnSave', 'enableDiagnostics', 'theme',
    ];
    for (const key of targets) {
      if (settings[key] !== undefined) {
        await config.update(key, settings[key], vscode.ConfigurationTarget.Global);
      }
    }
    this._postMessage({ type: 'settingsSaved' });
  }

  /**
   * Same on-disk location dabba/agent/mcp_client.py's MCP_CONFIG_PATH reads
   * from — mirrors dabba/utils/paths.py's get_dabba_config_dir() exactly.
   * Keep these two in sync: diverging here means the extension's Add/Delete/
   * Reload MCP Server buttons silently write to a file the backend never
   * reads.
   */
  private _dabbaConfigDir(): string {
    if (process.platform === 'win32') {
      const base = process.env.APPDATA;
      return path.join(base || path.join(os.homedir(), 'AppData', 'Roaming'), 'dabba');
    }
    if (process.platform === 'darwin') {
      return path.join(os.homedir(), 'Library', 'Application Support', 'dabba');
    }
    const base = process.env.XDG_CONFIG_HOME;
    return path.join(base || path.join(os.homedir(), '.config'), 'dabba');
  }

  private _mcpConfigPath(): string {
    return path.join(this._dabbaConfigDir(), 'mcp_servers.json');
  }

  private _readMcpConfig(): { mcpServers: Record<string, { command: string; args: string[]; env?: Record<string, string> }> } {
    try {
      const raw = fs.readFileSync(this._mcpConfigPath(), 'utf-8');
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object' && parsed.mcpServers) { return parsed; }
    } catch { /* missing or corrupt — treat as no servers configured yet */ }
    return { mcpServers: {} };
  }

  private _writeMcpConfig(config: { mcpServers: Record<string, unknown> }): void {
    const configPath = this._mcpConfigPath();
    fs.mkdirSync(path.dirname(configPath), { recursive: true });
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf-8');
  }

  private async _mcpApiHeaders(): Promise<Record<string, string>> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    const apiKey = await this.settings.getApiKey();
    if (apiKey) { headers['Authorization'] = `Bearer ${apiKey}`; }
    return headers;
  }

  /**
   * Merge the on-disk config (source of truth for what's configured) with
   * live connection status from the server (source of truth for what's
   * actually connected) and push the combined view to the MCP panel.
   */
  private async _sendMcpDataToPanel(): Promise<void> {
    const config = this._readMcpConfig();
    const configured = Object.entries(config.mcpServers).map(([name, cfg]) => ({
      name,
      command: cfg.command,
      args: cfg.args || [],
      connected: false,
      tools: [] as string[],
    }));

    try {
      const settings = this.settings.getSettings();
      const resp = await fetch(`${settings.apiEndpoint}/v1/mcp/status`, { headers: await this._mcpApiHeaders() });
      if (resp.ok) {
        const data = await resp.json() as { servers: Array<{ name: string; connected: boolean; tools: string[] }> };
        const liveByName = new Map(data.servers.map(s => [s.name, s]));
        for (const entry of configured) {
          const live = liveByName.get(entry.name);
          if (live) { entry.connected = live.connected; entry.tools = live.tools; }
        }
        this._postMessage({ type: 'mcpData', servers: configured, configPath: this._mcpConfigPath(), serverReachable: true });
        return;
      }
    } catch { /* server not running — still show configured servers, just as not-connected */ }

    this._postMessage({ type: 'mcpData', servers: configured, configPath: this._mcpConfigPath(), serverReachable: false });
  }

  /** Add one server entry to mcp_servers.json and connect it immediately (no restart needed for new entries). */
  private async _addMcpServer(name: string, command: string, argsText: string, envText: string): Promise<void> {
    name = (name || '').trim();
    command = (command || '').trim();
    if (!name || !command) {
      this._postMessage({ type: 'mcpError', content: 'Name and command are required.' });
      return;
    }

    const args = (argsText || '').split(/\s+/).filter(Boolean);
    const env: Record<string, string> = {};
    for (const line of (envText || '').split('\n')) {
      const idx = line.indexOf('=');
      if (idx > 0) { env[line.slice(0, idx).trim()] = line.slice(idx + 1).trim(); }
    }

    const config = this._readMcpConfig();
    config.mcpServers[name] = { command, args, ...(Object.keys(env).length ? { env } : {}) };
    this._writeMcpConfig(config);

    await this._reloadMcpServers();
  }

  /** Remove a server entry from mcp_servers.json. If it's already connected this session, it stays connected until restart. */
  private async _deleteMcpServer(name: string): Promise<void> {
    const config = this._readMcpConfig();
    delete config.mcpServers[name];
    this._writeMcpConfig(config);
    await this._sendMcpDataToPanel();
  }

  /** Tell the server to re-read mcp_servers.json and connect any newly-added servers, then refresh the panel. */
  private async _reloadMcpServers(): Promise<void> {
    try {
      const settings = this.settings.getSettings();
      const resp = await fetch(`${settings.apiEndpoint}/v1/mcp/reload`, {
        method: 'POST',
        headers: await this._mcpApiHeaders(),
      });
      if (!resp.ok) {
        this._postMessage({ type: 'mcpError', content: `Server returned status ${resp.status}` });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      this._postMessage({ type: 'mcpError', content: `Could not reach Dabba server: ${msg}` });
    }
    await this._sendMcpDataToPanel();
  }

  /**
   * Picks which workspace folder file-relative operations should resolve
   * against. In a multi-root workspace, "always folders[0]" silently
   * resolves relative paths in the wrong root whenever the active file
   * lives in a different folder — so prefer the folder containing the
   * active editor's file, falling back to the first folder only when
   * there's no active editor (or it's not in a workspace folder at all,
   * e.g. an unsaved buffer).
   */
  private _primaryWorkspaceFolder(): vscode.WorkspaceFolder | undefined {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) { return undefined; }
    const editor = vscode.window.activeTextEditor;
    if (editor) {
      const owning = vscode.workspace.getWorkspaceFolder(editor.document.uri);
      if (owning) { return owning; }
    }
    return folders[0];
  }

  private _editorContext(): { workspace?: string; active_file?: string; selection?: string } {
    const ctx: { workspace?: string; active_file?: string; selection?: string } = {};
    const primary = this._primaryWorkspaceFolder();
    if (primary) { ctx.workspace = primary.uri.fsPath; }
    const editor = vscode.window.activeTextEditor;
    if (editor) {
      ctx.active_file = editor.document.uri.fsPath;
      const sel = editor.document.getText(editor.selection);
      if (sel && sel.trim().length > 0 && sel.length < 8000) { ctx.selection = sel; }
    }
    return ctx;
  }

  /** Answers the webview's 'getContextPreview' — what would be sent right now if the user hit send. */
  private _sendContextPreview(): void {
    const ctx = this._editorContext();
    const pinned = this._readPinnedFiles();
    this._postMessage({
      type: 'contextPreview',
      activeFile: ctx.active_file ? vscode.workspace.asRelativePath(ctx.active_file, false) : undefined,
      selectionChars: ctx.selection ? ctx.selection.length : 0,
      pinnedFiles: pinned.map((p) => p.relativePath),
      pinnedChars: pinned.reduce((sum, p) => sum + p.content.length, 0),
    });
  }

  private async _resolveMentionFile(relativePath: string): Promise<void> {
    const primary = this._primaryWorkspaceFolder();
    if (!primary) { return; }
    const fullPath = path.isAbsolute(relativePath) ? relativePath : path.join(primary.uri.fsPath, relativePath);
    try {
      const content = fs.readFileSync(fullPath, 'utf-8');
      this._postMessage({ type: 'mentionFileContent', relativePath, content: content.slice(0, 8000) });
    } catch {
      this._postMessage({ type: 'mentionFileContent', relativePath, content: '(could not read file)' });
    }
  }

  private async _handleViewDiff(relativePath: string, proposedContent: string): Promise<void> {
    const primary = this._primaryWorkspaceFolder();
    if (!primary) { return; }
    const fullPath = path.isAbsolute(relativePath) ? relativePath : path.join(primary.uri.fsPath, relativePath);
    await this._diffManager.showDiff(fullPath, proposedContent);
  }

  /**
   * Open a changed-files chip's file, or a generated artifact's "Open File"
   * button. PDF/DOCX/XLSX/PPTX go through the OS's own default application
   * (vscode.env.openExternal) — openTextDocument would render their binary
   * bytes as garbled text, which is worse than not opening anything.
   */
  private async _openFile(relativePath: string): Promise<void> {
    const primary = this._primaryWorkspaceFolder();
    if (!primary) { return; }
    const fullPath = path.isAbsolute(relativePath) ? relativePath : path.join(primary.uri.fsPath, relativePath);
    const ext = path.extname(fullPath).toLowerCase();

    try {
      if (BINARY_EXTENSIONS.has(ext)) {
        const opened = await vscode.env.openExternal(vscode.Uri.file(fullPath));
        if (!opened) {
          vscode.window.showWarningMessage(
            `Could not open ${relativePath} with an external application. It was created at ${fullPath}.`,
          );
        }
        return;
      }
      const doc = await vscode.workspace.openTextDocument(fullPath);
      await vscode.window.showTextDocument(doc);
    } catch (err) {
      vscode.window.showErrorMessage(`Could not open ${relativePath}: ${err}`);
    }
  }

  /**
   * Show the permission card. Unlike the old version, this does NOT block —
   * the server itself is genuinely paused (its async generator hasn't
   * advanced past the tool_call yield), so nothing executes until
   * _sendApproval posts a real decision back to /v1/agent/approve.
   */
  private _requestPermission(callId: string, toolName: string, args: Record<string, unknown>, untrustedWorkspace: boolean): void {
    this._pendingApprovalCallIds.add(callId);
    this._postMessage({ type: 'permissionRequired', callId, toolName, args, untrustedWorkspace });
  }

  /** Send the user's Allow/Deny decision to the server, unblocking its paused tool call. */
  private async _sendApproval(callId: string, approved: boolean): Promise<void> {
    const settings = this.settings.getSettings();
    this._pendingApprovalCallIds.delete(callId);
    try {
      const apiKey = await this.settings.getApiKey();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (apiKey) { headers['Authorization'] = `Bearer ${apiKey}`; }
      await fetch(`${settings.apiEndpoint}/v1/agent/approve`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ call_id: callId, approved }),
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      this._postMessage({ type: 'agentError', content: `Could not send approval: ${msg}` });
    }
  }

  // How long to wait for the server to start responding at all before giving
  // up — separate from the stream's total duration, which can legitimately
  // run for minutes on a long agent turn.
  private static readonly CONNECT_TIMEOUT_MS = 20_000;

  /** Called once a turn's stream completes successfully — shows every file
   * changed this turn as one batched multi-file diff (see DiffManager.showBatchDiff). */
  private async _finishTurn(): Promise<void> {
    const edits = Array.from(this._turnEdits.values());
    this._lastTurnEdits = edits;
    this._turnEdits.clear();
    if (edits.length > 0) {
      await this._diffManager.showBatchDiff(edits).catch(() => {});
    }
  }

  private async _runAgent(
    text: string,
    attachments: Array<{ name: string; path: string; isImage: boolean; base64Data?: string }> = [],
    mentions: Array<{ relativePath: string; content: string }> = [],
  ): Promise<void> {
    this._lastRequest = { text, attachments, mentions };
    this._turnEdits.clear();
    this._postMessage({ type: 'addMessage', role: 'user', content: text, attachments, mentions });
    this._postMessage({ type: 'agentStart' });

    let augmentedText = text;

    // Inject pinned file contents — read fresh every turn (not cached from
    // whenever they were pinned), unlike one-shot @-mentions below.
    const pinned = this._readPinnedFiles();
    if (pinned.length > 0) {
      const pinnedParts = pinned.map((p) =>
        `[Pinned file: ${p.relativePath}]\n\`\`\`\n${p.content}\n\`\`\``
      );
      augmentedText = pinnedParts.join('\n\n') + '\n\n' + augmentedText;
    }

    // Inject mention file contents
    if (mentions && mentions.length > 0) {
      const mentionParts = mentions.map(m =>
        `[File: ${m.relativePath}]\n\`\`\`\n${m.content}\n\`\`\``
      );
      augmentedText = mentionParts.join('\n\n') + '\n\n' + augmentedText;
    }

    // Inject attachment references
    if (attachments && attachments.length > 0) {
      const attParts = attachments.map(att =>
        att.isImage
          ? `[Attached Image: ${att.name} (at ${att.path})]`
          : `[Attached File: ${att.name} (at ${att.path})]`
      );
      augmentedText = attParts.join('\n') + '\n\n' + augmentedText;
    }

    const startTime = Date.now();
    const first = await this._streamAgentRequest(augmentedText, startTime);

    if (first.kind === 'ok') {
      await this._finishTurn();
      return;
    }
    if (first.kind === 'aborted') {
      return; // _streamAgentRequest already posted agentInterrupted/agentEnd.
    }

    if (first.kind === 'midstream-drop') {
      // One silent reconnect attempt — the server has no resume token, so
      // this re-sends the same turn rather than resuming a partial one.
      this._postMessage({ type: 'agentText', content: '\n\n_[connection dropped — reconnecting…]_\n\n' });
      const retry = await this._streamAgentRequest(augmentedText, startTime);
      if (retry.kind === 'ok') {
        await this._finishTurn();
        return;
      }
      if (retry.kind === 'aborted') {
        return;
      }
      this._postMessage({ type: 'agentError', content: retry.message, retryable: true });
      this._postMessage({ type: 'agentEnd', elapsed: Math.round((Date.now() - startTime) / 1000) });
      return;
    }

    // 'network' or 'http' — surfaced immediately, no automatic retry (an
    // unreachable server or bad auth won't fix itself on a second attempt).
    this._postMessage({ type: 'agentError', content: first.message, retryable: first.kind === 'network' });
    this._postMessage({ type: 'agentEnd', elapsed: Math.round((Date.now() - startTime) / 1000) });
  }

  /**
   * Runs one full request/stream attempt against /v1/agent.
   *
   * Distinguishes failure classes because they need different treatment:
   * - 'network': connection never established (unreachable server, DNS,
   *   connect timeout) — showing "is the server running?" is accurate here.
   * - 'http': server responded but with an error status (401 gets a
   *   dedicated re-auth prompt; others show the raw status).
   * - 'midstream-drop': the connection was live and producing events, then
   *   died — worth one automatic retry, unlike the other failure kinds.
   * - 'aborted': the user hit Stop, or the connect timeout fired, or the
   *   extension is shutting down (see _abortReason).
   * - 'ok': the stream completed normally; agentEnd was already posted.
   */
  private async _streamAgentRequest(
    augmentedText: string,
    startTime: number,
  ): Promise<{ kind: 'ok' } | { kind: 'aborted' } | { kind: 'network' | 'http' | 'midstream-drop'; message: string }> {
    const settings = this.settings.getSettings();
    const endpoint = `${settings.apiEndpoint}/v1/agent`;
    this._abort = new AbortController();
    this._abortReason = undefined;

    const connectTimer = setTimeout(() => {
      this._abortReason = 'timeout';
      this._abort?.abort();
    }, ChatViewProvider.CONNECT_TIMEOUT_MS);

    let receivedAnyEvent = false;

    try {
      const apiKey = await this.settings.getApiKey();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (apiKey) { headers['Authorization'] = `Bearer ${apiKey}`; }

      let response: Response;
      try {
        response = await fetch(endpoint, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            message: augmentedText,
            model: settings.model !== 'dabba' ? settings.model : undefined,
            effort: settings.effort,
            permission_mode: this._permissionMode,
            ...this._editorContext(),
          }),
          signal: this._abort.signal,
        });
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError' && this._abortReason !== 'timeout') {
          this._postMessage({ type: 'agentInterrupted' });
          this._postMessage({ type: 'agentEnd', elapsed: Math.round((Date.now() - startTime) / 1000) });
          return { kind: 'aborted' };
        }
        return {
          kind: 'network',
          message: this._abortReason === 'timeout'
            ? `Timed out waiting for the Dabba server at ${settings.apiEndpoint} to respond.`
            : `Cannot reach the Dabba server at ${settings.apiEndpoint}. ` +
              `Is it running? Start it with: python3 -m dabba.api.server`,
        };
      }
      clearTimeout(connectTimer);

      if (response.status === 401) {
        vscode.window.showWarningMessage(
          'Dabba: API key was rejected (401). Set a new key?',
          'Set API Key',
        ).then((choice) => {
          if (choice === 'Set API Key') {
            vscode.commands.executeCommand('dabba.setApiKey');
          }
        });
        return { kind: 'http', message: 'Authentication failed (401) — API key was rejected or missing.' };
      }
      if (!response.ok || !response.body) {
        return { kind: 'http', message: `Server error ${response.status}.` };
      }

      const reader = (response.body as ReadableStream<Uint8Array>).getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      for (;;) {
        const { done, value } = await reader.read();
        if (done) { break; }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          const data = line.replace(/^data:\s*/, '').trim();
          if (!data) { continue; }
          try {
            const event = JSON.parse(data);
            receivedAnyEvent = true;
            await this._handleAgentEvent(event, startTime);
          } catch { /* skip malformed */ }
        }
      }
      this._postMessage({ type: 'agentEnd', elapsed: Math.round((Date.now() - startTime) / 1000) });
      return { kind: 'ok' };
    } catch (err) {
      const aborted = err instanceof Error && err.name === 'AbortError';
      if (aborted && this._abortReason !== 'timeout') {
        this._postMessage({ type: 'agentInterrupted' });
        return { kind: 'aborted' };
      }
      const msg = err instanceof Error ? err.message : 'Unknown error';
      if (receivedAnyEvent) {
        return { kind: 'midstream-drop', message: msg };
      }
      return {
        kind: aborted ? 'network' : 'http', // timeout abort surfaces as a connect-style failure
        message: aborted
          ? `Timed out waiting for the Dabba server at ${settings.apiEndpoint} to respond.`
          : msg,
      };
    } finally {
      clearTimeout(connectTimer);
    }
  }

  private async _handleAgentEvent(event: { type: string; content: unknown }, startTime: number): Promise<void> {
    switch (event.type) {
      case 'text':
        this._postMessage({ type: 'agentText', content: event.content });
        break;

      case 'tool_call': {
        const c = event.content as { name?: string; arguments?: Record<string, unknown>; call_id?: string };
        const toolName = c?.name ?? 'tool';
        const args = c?.arguments ?? {};
        // The server always assigns a real call_id now (agent_loop.py) — this
        // is the same id it's paused on server-side awaiting /v1/agent/approve.
        const callId = c?.call_id ?? (toolName + '_' + Date.now());
        const thought = Math.round((Date.now() - startTime) / 1000);

        this._postMessage({
          type: 'toolCall',
          callId,
          name: toolName,
          args,
          thought,
          isDangerous: isDangerousTool(toolName),
          isEdit: EDIT_TOOLS.has(toolName),
        });

        // Capture the file's content now, before the server executes this edit,
        // so we can show a real before/after diff once it's done.
        if (EDIT_TOOLS.has(toolName) && typeof args.path === 'string') {
          const primary = this._primaryWorkspaceFolder();
          if (primary) {
            const fullPath = path.isAbsolute(args.path) ? args.path : path.join(primary.uri.fsPath, args.path);
            let before = '';
            try {
              if (fs.existsSync(fullPath)) { before = fs.readFileSync(fullPath, 'utf-8'); }
            } catch { /* new file — before stays empty */ }
            this._pendingEdits.set(callId, { filePath: fullPath, before });
          }
        }

        // The server is genuinely blocked on this call_id right now (see
        // agent_endpoints.py event_gen) — show the approval card. No local
        // await here: the pause lives server-side, not in this function.
        //
        // Workspace trust can't stop the server from having already run
        // something (trust is a VS Code editor concept the Python backend
        // has no notion of), but it CAN force a real decision here instead
        // of letting 'auto' mode silently wave through a dangerous call in
        // a workspace the user hasn't vouched for.
        const untrustedWorkspace = !vscode.workspace.isTrusted;
        if (isDangerousTool(toolName) && (this._permissionMode === 'ask' || untrustedWorkspace)) {
          this._requestPermission(callId, toolName, args, untrustedWorkspace);
        }
        break;
      }

      case 'tool_result': {
        const r = event.content as { tool?: string; tool_name?: string; call_id?: string; success?: boolean; output?: unknown; error?: string };
        const toolName = r?.tool ?? r?.tool_name ?? 'tool';
        const output = typeof r?.output === 'string' ? r.output : JSON.stringify(r?.output ?? r?.error ?? '', null, 2);
        const pending = r?.call_id ? this._pendingEdits.get(r.call_id) : undefined;
        if (r?.call_id) { this._pendingEdits.delete(r.call_id); }

        // Todo-list tool results additionally render as a live checklist widget
        if ((toolName === 'todo_write' || toolName === 'todo_update') && r?.success !== false) {
          try {
            const parsed = JSON.parse(output);
            if (Array.isArray(parsed?.todos)) {
              this._postMessage({ type: 'todoUpdate', todos: parsed.todos });
            }
          } catch { /* malformed — the generic tool card below still shows raw output */ }
        }

        const relativeFilePath = pending
          ? vscode.workspace.asRelativePath(pending.filePath, false)
          : undefined;

        // Artifact tools (markdown_to_pdf/markdown_to_docx) return their
        // output path in the JSON result rather than via the file_write/
        // file_edit _pendingEdits mechanism — pull it out so there's
        // SOMETHING to open, which previously didn't exist for these tools.
        let artifactPath: string | undefined;
        if (ARTIFACT_TOOLS.has(toolName) && r?.success !== false) {
          try {
            const parsedOutput = JSON.parse(output) as { path?: string };
            if (typeof parsedOutput.path === 'string') {
              artifactPath = vscode.workspace.asRelativePath(parsedOutput.path, false);
            }
          } catch { /* malformed output — no path to offer */ }
        }

        this._postMessage({
          type: 'toolResult',
          name: toolName,
          success: r?.success !== false,
          output,
          filePath: relativeFilePath ?? artifactPath,
          isEdit: EDIT_TOOLS.has(toolName),
          isArtifact: ARTIFACT_TOOLS.has(toolName) && !!artifactPath,
        });

        if (EDIT_TOOLS.has(toolName) && pending && r?.success !== false) {
          // Track file changes for the "changed files" chip row
          this._changedFiles.add(relativeFilePath!);
          this._postMessage({ type: 'fileChanged', filePath: relativeFilePath, changedFiles: Array.from(this._changedFiles) });

          // Record before/after for a single batched multi-file diff shown
          // once the whole turn finishes, instead of popping open a diff tab
          // after every individual edit (disruptive when the agent touches
          // several files in one turn). Keep the ORIGINAL before-content if
          // this file was already edited earlier this turn.
          try {
            const after = fs.existsSync(pending.filePath) ? fs.readFileSync(pending.filePath, 'utf-8') : '';
            const existing = this._turnEdits.get(pending.filePath);
            this._turnEdits.set(pending.filePath, {
              filePath: pending.filePath,
              before: existing ? existing.before : pending.before,
              after,
            });
          } catch { /* file may have been deleted immediately after; skip the diff */ }
        } else if (artifactPath) {
          // No diff for binary artifacts, but still surface it in the
          // changed-files chip row so there's at least one way to open it.
          this._changedFiles.add(artifactPath);
          this._postMessage({ type: 'fileChanged', filePath: artifactPath, changedFiles: Array.from(this._changedFiles) });
        }
        break;
      }

      case 'plan': {
        const steps = event.content as string[];
        this._postMessage({ type: 'agentPlan', steps });
        break;
      }

      case 'usage': {
        const u = event.content as { input_tokens?: number; output_tokens?: number };
        this._postMessage({ type: 'tokenUsage', inputTokens: u?.input_tokens ?? 0, outputTokens: u?.output_tokens ?? 0 });
        break;
      }

      case 'error':
        this._postMessage({ type: 'agentError', content: String(event.content) });
        break;
      case 'tool_denied': {
        const d = event.content as { call_id?: string; name?: string } | string;
        const deniedName = typeof d === 'string' ? d : (d?.name ?? 'tool');
        this._postMessage({ type: 'agentError', content: `Tool denied: ${deniedName}` });
        break;
      }
    }
  }

  private async _resetAgent(): Promise<void> {
    const settings = this.settings.getSettings();
    try {
      const apiKey = await this.settings.getApiKey();
      const headers: Record<string, string> = {};
      if (apiKey) { headers['Authorization'] = `Bearer ${apiKey}`; }
      await fetch(`${settings.apiEndpoint}/v1/agent/reset`, { method: 'POST', headers });
    } catch { /* server may be down */ }
  }

  private async _loadModels(): Promise<void> {
    const settings = this.settings.getSettings();
    try {
      const apiKey = await this.settings.getApiKey();
      const headers: Record<string, string> = {};
      if (apiKey) { headers['Authorization'] = `Bearer ${apiKey}`; }
      const resp = await fetch(`${settings.apiEndpoint}/v1/agent/models`, { headers });
      if (resp.ok) {
        const data = await resp.json();
        this._postMessage({ type: 'modelsLoaded', ...data as object });
        return;
      }
      throw new Error(`Server returned status ${resp.status}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      this._postMessage({ type: 'modelsLoadError', error: `Could not load models: ${msg}. Is the Dabba server running at ${settings.apiEndpoint}?` });
    }
  }

  private async _setModel(model: string): Promise<void> {
    await vscode.workspace.getConfiguration('dabba').update('model', model, vscode.ConfigurationTarget.Global);
    this._postMessage({ type: 'modelSet', model });
  }

  private async _setEffort(effort: string): Promise<void> {
    await vscode.workspace.getConfiguration('dabba').update('effort', effort, vscode.ConfigurationTarget.Global);
    this._postMessage({ type: 'effortSet', effort });
  }

  private _postMessage(message: Record<string, unknown>): void {
    this._view?.webview.postMessage(message);
    if (typeof message.type === 'string' && PERSISTABLE_EVENTS.has(message.type)) {
      this._record(message);
    }
  }

  private async _insertCodeAtCursor(code: string): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
      editor.edit((editBuilder) => { editBuilder.insert(editor.selection.active, code); });
    }
  }

  private async _attachFile(): Promise<void> {
    const primary = this._primaryWorkspaceFolder();
    if (!primary) {
      vscode.window.showErrorMessage('Please open a workspace folder before attaching files.');
      return;
    }

    const fileUris = await vscode.window.showOpenDialog({
      canSelectMany: false,
      openLabel: 'Attach to Chat',
      filters: {
        'All Files': ['*'],
        'Images': ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'],
        'Source Code/Text': ['txt', 'js', 'ts', 'py', 'java', 'cpp', 'h', 'go', 'rs', 'html', 'css', 'json', 'yaml', 'yml', 'md'],
      }
    });

    if (!fileUris || fileUris.length === 0) { return; }

    const fileUri = fileUris[0];
    const originalPath = fileUri.fsPath;
    let finalPath = originalPath;
    const filename = path.basename(originalPath);

    // Pick whichever workspace folder actually contains the file (any root,
    // not just the primary one) — only fall back to copying into the
    // primary folder's attachments/ dir when the file is outside all of them.
    const owningFolder = vscode.workspace.getWorkspaceFolder(fileUri);
    const relativeBase = (owningFolder ?? primary).uri.fsPath;

    if (!owningFolder) {
      const attachmentsDir = path.join(relativeBase, 'attachments');
      if (!fs.existsSync(attachmentsDir)) { fs.mkdirSync(attachmentsDir, { recursive: true }); }
      finalPath = path.join(attachmentsDir, filename);
      try { fs.copyFileSync(originalPath, finalPath); } catch (err) {
        vscode.window.showErrorMessage(`Failed to copy attachment to workspace: ${err}`);
        return;
      }
    }

    const relativePath = path.relative(relativeBase, finalPath);
    const ext = path.extname(filename).substring(1).toLowerCase();
    const isImage = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext);

    let base64Data = '';
    if (isImage) {
      try {
        const fileBuffer = fs.readFileSync(finalPath);
        base64Data = `data:image/${ext === 'svg' ? 'svg+xml' : ext};base64,${fileBuffer.toString('base64')}`;
      } catch (err) {
        vscode.window.showErrorMessage(`Failed to read image preview: ${err}`);
      }
    }

    this._postMessage({ type: 'fileAttached', name: filename, path: relativePath, isImage, base64Data });
  }

  /**
   * Start recording from the default microphone via `arecord` (ALSA — ships
   * with essentially every Linux distro; no bundled dependency needed).
   * Recording happens here on the extension host, not in the webview — see
   * the class-level comment on _recordingProcess for why.
   */
  private _startVoiceRecording(): void {
    if (this._recordingProcess) { return; } // already recording

    const tmpPath = path.join(os.tmpdir(), `dabba-voice-${Date.now()}.wav`);
    const proc = spawn('arecord', ['-f', 'cd', '-t', 'wav', tmpPath]);

    // spawn() never throws synchronously for a missing binary — Node reports
    // that asynchronously via this 'error' event instead, so recording state
    // is set optimistically below and unwound here if it turns out to fail.
    proc.on('error', (err: NodeJS.ErrnoException) => {
      const msg = err.code === 'ENOENT'
        ? "Voice input needs 'arecord' (ALSA utils) — install it with your system package manager, e.g. `sudo apt-get install alsa-utils`."
        : `Could not start recording: ${err.message}`;
      this._postMessage({ type: 'voiceError', content: msg });
      this._recordingProcess = undefined;
      this._recordingPath = undefined;
    });

    this._recordingProcess = proc;
    this._recordingPath = tmpPath;
  }

  /** Stop the active recording, transcribe it, and send the text back to the webview's input box. */
  private async _stopVoiceRecording(): Promise<void> {
    const proc = this._recordingProcess;
    const recPath = this._recordingPath;
    this._recordingProcess = undefined;
    this._recordingPath = undefined;

    if (!proc || !recPath) { return; }

    await new Promise<void>((resolve) => {
      // A process that failed to spawn (e.g. arecord missing) never emits
      // 'exit', only 'error' — race both so this can't hang forever.
      proc.once('exit', () => resolve());
      proc.once('error', () => resolve());
      proc.kill('SIGINT'); // arecord flushes a valid WAV header on SIGINT — verified, not a guess
    });

    try {
      const audioBuffer = fs.readFileSync(recPath);
      if (audioBuffer.length === 0) {
        this._postMessage({ type: 'voiceError', content: 'No audio recorded — check your microphone.' });
        return;
      }

      const settings = this.settings.getSettings();
      const apiKey = await this.settings.getApiKey();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (apiKey) { headers['Authorization'] = `Bearer ${apiKey}`; }

      const resp = await fetch(`${settings.apiEndpoint}/v1/transcribe`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ audio_base64: audioBuffer.toString('base64') }),
      });

      if (!resp.ok) {
        this._postMessage({ type: 'voiceError', content: `Server returned status ${resp.status}` });
        return;
      }

      const data = await resp.json() as { text?: string; error?: string };
      if (data.error) {
        this._postMessage({ type: 'voiceError', content: data.error });
      } else {
        this._postMessage({ type: 'voiceTranscript', text: data.text || '' });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      this._postMessage({ type: 'voiceError', content: `Transcription failed: ${msg}` });
    } finally {
      fs.unlink(recPath, () => { /* best-effort cleanup */ });
    }
  }

  private _getHtmlContent(webview: vscode.Webview): string {
    const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'media', 'style.css'));
    const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'media', 'main.js'));

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource}; font-src ${webview.cspSource}; img-src ${webview.cspSource} data:; blob-src ${webview.cspSource};">
  <link rel="stylesheet" href="${styleUri}">
  <title>dabba AI</title>
</head>
<body>
  <div id="app">
    <div id="header">
      <div class="header-left">
        <span class="logo" aria-hidden="true">◇</span>
        <span class="title">dabba</span>
        <span id="connection-badge" class="connection-badge checking" role="status"><span class="connection-dot"></span><span class="connection-label">Checking</span></span>
      </div>
      <div class="header-right">
        <button id="newSessionBtn" class="header-action" title="New session" aria-label="New chat">＋ <span>New</span></button>
        <button id="moreBtn" class="icon-btn" title="More actions" aria-label="More actions" aria-expanded="false">•••</button>
        <div id="header-menu" class="header-menu hidden" role="menu">
          <button id="mcpBtn" role="menuitem"><span aria-hidden="true">◇</span> MCP servers</button>
          <button id="settingsBtn" role="menuitem"><span aria-hidden="true">⚙</span> Settings</button>
          <button id="deleteHistoryBtn" class="danger-menu-item" role="menuitem"><span aria-hidden="true">×</span> Delete history</button>
        </div>
      </div>
    </div>
    <div id="session-bar">
      <button id="historyBtn" class="session-switcher" aria-haspopup="listbox" aria-expanded="false">
        <span class="session-switcher-icon" aria-hidden="true">▤</span>
        <span id="active-session-label">Current session</span>
        <span aria-hidden="true">⌄</span>
      </button>
    </div>
    <div id="history-dropdown" class="hidden"></div>
    <div id="session-tabs" class="hidden" aria-hidden="true"></div>
    <div id="changed-files-bar" class="hidden"></div>
    <div id="messages">
      <div id="welcome-state" class="welcome-state">
        <div class="welcome-mark" aria-hidden="true">◇</div>
        <h2>Build with Dabba</h2>
        <p>Ask about your workspace, make a change, or start with a common task.</p>
        <div class="welcome-actions">
          <button data-prompt="Explain the selected code clearly">Explain selection</button>
          <button data-prompt="Review the active file and identify bugs or risks">Review active file</button>
          <button data-prompt="Fix the current problem and verify the result">Fix a problem</button>
          <button data-prompt="Generate useful tests for the active file">Generate tests</button>
        </div>
        <div class="welcome-hint"><span>Tip:</span> use <kbd>@</kbd> for files and <kbd>/</kbd> for commands</div>
      </div>
    </div>
    <div id="regen-row" class="hidden">
      <button id="regenBtn" title="Discard the last response and try again">↻ Regenerate</button>
    </div>
    <div id="status-bar" class="hidden">
      <span class="spinner"></span>
      <span class="status-copy"><strong id="status-phase">Working</strong><span id="status-text">Preparing request…</span></span>
      <span id="status-elapsed">0s</span>
      <span id="token-counter" class="hidden">
        <span id="token-in">↑0</span><span id="token-out">↓0</span>
      </span>
      <button id="stopBtn" title="Stop">◼</button>
    </div>
    <div id="input-area">
      <div id="attachments-container" class="hidden"></div>
      <div id="pinned-files-container" class="hidden"></div>
      <div id="mentions-container" class="hidden"></div>
      <div id="at-picker" class="hidden"></div>
      <div id="slash-picker" class="hidden"></div>
      <div id="selectors-row">
        <div class="selector-wrapper">
          <button id="modelBtn" class="model-chip" title="Switch model">dabba ▾</button>
          <div id="model-picker" class="hidden"></div>
        </div>
        <div class="selector-wrapper">
          <button id="effortBtn" class="model-chip" title="Switch reasoning effort">medium ▾</button>
          <div id="effort-picker" class="hidden"></div>
        </div>
        <span id="session-token-total" class="session-token-total" title="Total tokens this session"></span>
        <button id="optionsBtn" class="options-btn" aria-expanded="false" aria-controls="selectors-row">Generation options</button>
      </div>
      <div id="composer">
        <textarea id="message-input" rows="1" placeholder="Ask dabba… (@ to mention files, / for commands)"></textarea>
        <button id="micBtn" class="mic-btn" title="Voice input" aria-label="Voice input">◉</button>
        <div id="composer-toolbar">
          <div id="attach-menu-wrapper" style="position:relative;">
            <button id="attachBtn" class="composer-icon-btn" title="Add context" aria-label="Add context" aria-expanded="false">＋</button>
            <div id="attach-dropdown" class="hidden">
              <div class="attach-menu-item" id="attachWorkflowBtn">
                <span class="attach-menu-icon">⚡</span>
                <div class="attach-menu-text">
                  <span class="attach-menu-title">Workflows</span>
                  <span class="attach-menu-desc">Run a saved workflow</span>
                </div>
              </div>
              <div class="attach-menu-item" id="attachMediaBtn">
                <span class="attach-menu-icon">📎</span>
                <div class="attach-menu-text">
                  <span class="attach-menu-title">Media</span>
                  <span class="attach-menu-desc">Attach an image or file</span>
                </div>
              </div>
              <div class="attach-menu-item" id="attachMentionBtn">
                <span class="attach-menu-icon">@</span>
                <div class="attach-menu-text">
                  <span class="attach-menu-title">Mentions</span>
                  <span class="attach-menu-desc">Reference a file in your workspace</span>
                </div>
              </div>
            </div>
          </div>
          <button id="diffModeBtn" class="composer-icon-btn" title="View changed files" aria-label="View changed files">▱</button>
          <span id="composer-spinner" class="composer-spinner hidden"></span>
          <span id="context-chip" class="composer-chip hidden"></span>
          <button id="permissionModeBtn" class="composer-chip permission-chip" title="Toggle approval mode">✋ Ask before edits</button>
          <span class="composer-spacer"></span>
          <button id="sendBtn" class="composer-send" title="Send (Enter)" aria-label="Send message">↑</button>
        </div>
      </div>
    </div>
  </div>

  <div id="settings-overlay" class="hidden">
    <div id="settings-panel">
      <div id="settings-header">
        <span>⚙ Settings</span>
        <button id="settingsCloseBtn" class="icon-btn" title="Close">✕</button>
      </div>
      <div id="settings-body">
        <div class="settings-group">
          <label class="settings-label">API Endpoint</label>
          <input type="text" id="set-apiEndpoint" class="settings-input" placeholder="http://localhost:8080">
        </div>
        <div class="settings-group">
          <label class="settings-label">API Key</label>
          <div id="settings-key-row">
            <input type="password" id="set-apiKey" class="settings-input" placeholder="Paste key to update">
            <button id="settings-key-save" class="settings-btn-small">Save</button>
          </div>
          <div id="settings-key-status" class="settings-hint"></div>
        </div>
        <div class="settings-group">
          <label class="settings-label">Default Effort</label>
          <select id="set-effort" class="settings-input">
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="xhigh">xhigh</option>
            <option value="max">max</option>
          </select>
        </div>
        <div class="settings-group">
          <label class="settings-label">Max Tokens</label>
          <input type="number" id="set-maxTokens" class="settings-input" min="128" max="128000">
        </div>
        <div class="settings-group">
          <label class="settings-label">Temperature</label>
          <input type="number" id="set-temperature" class="settings-input" min="0" max="2" step="0.1">
        </div>
        <div class="settings-group settings-row">
          <label class="settings-label">Auto-review on save</label>
          <input type="checkbox" id="set-autoReviewOnSave" class="settings-checkbox">
        </div>
        <div class="settings-group settings-row">
          <label class="settings-label">Enable diagnostics</label>
          <input type="checkbox" id="set-enableDiagnostics" class="settings-checkbox">
        </div>
        <div class="settings-group">
          <label class="settings-label">Theme</label>
          <select id="set-theme" class="settings-input">
            <option value="auto">auto</option>
            <option value="dark">dark</option>
            <option value="light">light</option>
          </select>
        </div>
        <div class="settings-actions">
          <button id="settings-save" class="settings-btn-primary">Save Settings</button>
          <button id="settings-advanced" class="settings-btn-ghost">Open native settings.json</button>
        </div>
      </div>
    </div>
  </div>

  <div id="mcp-overlay" class="hidden">
    <div id="mcp-panel">
      <div id="mcp-header">
        <span>🔌 MCP Servers</span>
        <button id="mcpCloseBtn" class="icon-btn" title="Close">✕</button>
      </div>
      <div id="mcp-body">
        <div id="mcp-server-list"></div>
        <div class="settings-hint" id="mcp-hint">
          Adding a server connects immediately. Editing/removing a server that's
          already connected needs a Dabba server restart to take effect.
        </div>
        <div class="mcp-add-form">
          <div class="settings-group">
            <label class="settings-label">Name</label>
            <input type="text" id="mcp-add-name" class="settings-input" placeholder="e.g. filesystem">
          </div>
          <div class="settings-group">
            <label class="settings-label">Command</label>
            <input type="text" id="mcp-add-command" class="settings-input" placeholder="npx">
          </div>
          <div class="settings-group">
            <label class="settings-label">Args (space-separated)</label>
            <input type="text" id="mcp-add-args" class="settings-input" placeholder="-y @modelcontextprotocol/server-filesystem /path">
          </div>
          <div class="settings-group">
            <label class="settings-label">Env (optional, one KEY=value per line)</label>
            <textarea id="mcp-add-env" class="settings-input" rows="2" placeholder="API_KEY=..."></textarea>
          </div>
          <div class="settings-actions">
            <button id="mcp-add-save" class="settings-btn-primary">+ Add Server</button>
            <button id="mcp-refresh" class="settings-btn-ghost">↻ Refresh / Connect New</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script src="${scriptUri}"></script>
</body>
</html>`;
  }
}
