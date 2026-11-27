import * as vscode from 'vscode';

export interface DabbaSettings {
  apiEndpoint: string;
  model: string;
  effort: string;
  maxTokens: number;
  temperature: number;
  autoReviewOnSave: boolean;
  enableDiagnostics: boolean;
  autoStartBackend: boolean;
  backendPython: string;
  theme: 'auto' | 'light' | 'dark';
}

const DEFAULT_SETTINGS: DabbaSettings = {
  apiEndpoint: 'http://127.0.0.1:8080',
  model: 'dabba',
  effort: 'medium',
  maxTokens: 4096,
  temperature: 0.7,
  autoReviewOnSave: false,
  enableDiagnostics: true,
  autoStartBackend: true,
  backendPython: 'python3',
  theme: 'auto',
};

export class SettingsManager {
  private _onDidChangeSettings = new vscode.EventEmitter<DabbaSettings>();
  readonly onDidChangeSettings: vscode.Event<DabbaSettings> = this._onDidChangeSettings.event;

  private secretStorage: vscode.SecretStorage;
  private configListener: vscode.Disposable;

  constructor(context: vscode.ExtensionContext) {
    this.secretStorage = context.secrets;
    this.configListener = vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('dabba')) {
        this._onDidChangeSettings.fire(this.getSettings());
      }
    });
  }

  getSettings(): DabbaSettings {
    const config = vscode.workspace.getConfiguration('dabba');
    const configuredEndpoint = config.get<string>('apiEndpoint', DEFAULT_SETTINGS.apiEndpoint);
    const apiEndpoint = configuredEndpoint.replace(/^http:\/\/localhost(?=[:/]|$)/, 'http://127.0.0.1');
    return {
      apiEndpoint,
      model: config.get<string>('model', DEFAULT_SETTINGS.model),
      effort: config.get<string>('effort', DEFAULT_SETTINGS.effort),
      maxTokens: config.get<number>('maxTokens', DEFAULT_SETTINGS.maxTokens),
      temperature: config.get<number>('temperature', DEFAULT_SETTINGS.temperature),
      autoReviewOnSave: config.get<boolean>('autoReviewOnSave', DEFAULT_SETTINGS.autoReviewOnSave),
      enableDiagnostics: config.get<boolean>('enableDiagnostics', DEFAULT_SETTINGS.enableDiagnostics),
      autoStartBackend: config.get<boolean>('autoStartBackend', DEFAULT_SETTINGS.autoStartBackend),
      backendPython: config.get<string>('backendPython', DEFAULT_SETTINGS.backendPython),
      theme: config.get<'auto' | 'light' | 'dark'>('theme', DEFAULT_SETTINGS.theme),
    };
  }

  async getApiKey(): Promise<string | undefined> {
    return (await this.secretStorage.get(this.sessionKey(this.getSettings().apiEndpoint))) ?? this.secretStorage.get('dabba.apiKey');
  }

  async setApiKey(key: string): Promise<void> {
    await this.secretStorage.store('dabba.apiKey', key);
  }

  async clearApiKey(): Promise<void> {
    await this.secretStorage.delete('dabba.apiKey');
  }

  private sessionKey(endpoint: string): string {
    return `dabba.session:${endpoint.replace(/\/+$/, '')}`;
  }

  async setSession(endpoint: string, token: string): Promise<void> {
    await this.secretStorage.store(this.sessionKey(endpoint), token);
  }

  async clearSession(endpoint: string): Promise<void> {
    await this.secretStorage.delete(this.sessionKey(endpoint));
  }

  dispose(): void {
    this.configListener.dispose();
    this._onDidChangeSettings.dispose();
  }
}
