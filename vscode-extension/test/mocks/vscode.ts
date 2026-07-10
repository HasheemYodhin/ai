/**
 * Minimal hand-written mock of the `vscode` module surface actually used by
 * src/*.ts — just enough to unit-test SettingsManager, DiffManager, and
 * ChatViewProvider's pure logic under vitest, without needing a real
 * Extension Host (@vscode/test-electron is the alternative for true
 * integration tests, but it needs a display and is much slower for CI).
 *
 * Extend this file's surface as new src/*.ts files start using vscode APIs
 * these tests need — don't try to mock the whole API up front.
 */
import { vi } from 'vitest';

export class EventEmitter<T> {
  private _listeners: Array<(e: T) => void> = [];
  event = (listener: (e: T) => void) => {
    this._listeners.push(listener);
    return { dispose: () => { this._listeners = this._listeners.filter((l) => l !== listener); } };
  };
  fire(data: T): void {
    for (const l of this._listeners) { l(data); }
  }
  dispose(): void { this._listeners = []; }
}

export class Uri {
  private constructor(public readonly fsPath: string, public readonly scheme = 'file') {}
  static file(path: string): Uri { return new Uri(path, 'file'); }
  static parse(value: string): Uri { return new Uri(value.replace(/^file:\/\//, ''), 'file'); }
  static joinPath(base: Uri, ...segments: string[]): Uri {
    return new Uri([base.fsPath, ...segments].join('/'), base.scheme);
  }
  toString(): string { return `${this.scheme}://${this.fsPath}`; }
}

export class Range {
  constructor(
    public startLine: number, public startCol: number,
    public endLine: number, public endCol: number,
  ) {}
  get start() { return { line: this.startLine, character: this.startCol }; }
  get end() { return { line: this.endLine, character: this.endCol }; }
}

export enum DiagnosticSeverity { Error = 0, Warning = 1, Information = 2, Hint = 3 }

export class Diagnostic {
  source?: string;
  code?: string | number;
  constructor(public range: Range, public message: string, public severity: DiagnosticSeverity) {}
}

export enum CodeActionKind {}
// Real vscode.CodeActionKind.QuickFix is a CodeActionKind instance, not a
// plain enum member — a string sentinel is enough for equality checks in tests.
(CodeActionKind as unknown as Record<string, string>).QuickFix = 'quickfix';

export class CodeAction {
  command?: { command: string; title: string; arguments?: unknown[] };
  diagnostics?: Diagnostic[];
  isPreferred?: boolean;
  constructor(public title: string, public kind?: string) {}
}

export enum StatusBarAlignment { Left = 1, Right = 2 }
export enum ConfigurationTarget { Global = 1, Workspace = 2, WorkspaceFolder = 3 }

export const workspace = {
  workspaceFolders: undefined as Array<{ uri: Uri; name: string; index: number }> | undefined,
  isTrusted: true,
  getConfiguration: vi.fn((_section?: string) => ({
    get: (_key: string, defaultValue: unknown) => defaultValue,
  })),
  onDidChangeConfiguration: vi.fn(() => ({ dispose: () => {} })),
  onDidSaveTextDocument: vi.fn(() => ({ dispose: () => {} })),
  getWorkspaceFolder: vi.fn(() => undefined),
  asRelativePath: vi.fn((uriOrPath: Uri | string) => {
    const p = typeof uriOrPath === 'string' ? uriOrPath : uriOrPath.fsPath;
    return p;
  }),
  findFiles: vi.fn(async () => [] as Uri[]),
  openTextDocument: vi.fn(async (uri: Uri) => ({ uri })),
};

export const window = {
  activeTextEditor: undefined as unknown,
  showInformationMessage: vi.fn(async () => undefined as string | undefined),
  showWarningMessage: vi.fn(async () => undefined as string | undefined),
  showErrorMessage: vi.fn(async () => undefined as string | undefined),
  showTextDocument: vi.fn(async () => ({ edit: vi.fn() })),
  showOpenDialog: vi.fn(async () => undefined as Uri[] | undefined),
  createStatusBarItem: vi.fn(() => ({ show: vi.fn(), hide: vi.fn(), dispose: vi.fn() })),
  onDidChangeActiveTextEditor: vi.fn(() => ({ dispose: () => {} })),
  registerWebviewViewProvider: vi.fn(() => ({ dispose: () => {} })),
};

export const commands = {
  executeCommand: vi.fn(async () => undefined),
  registerCommand: vi.fn(() => ({ dispose: () => {} })),
};

export const env = {
  openExternal: vi.fn(async () => true),
};

export const languages = {
  createDiagnosticCollection: vi.fn(() => ({
    set: vi.fn(),
    clear: vi.fn(),
    dispose: vi.fn(),
  })),
  registerCodeActionsProvider: vi.fn(() => ({ dispose: () => {} })),
};
