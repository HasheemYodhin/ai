import * as vscode from 'vscode';

export interface DabbaSettings {
  apiEndpoint: string;
  model: string;
  effort: string;
  maxTokens: number;
  temperature: number;
  autoReviewOnSave: boolean;
  enableDiagnostics: boolean;
  theme: 'auto' | 'light' | 'dark';
}

const DEFAULT_SETTINGS: DabbaSettings = {
  apiEndpoint: 'http://localhost:8080',
  model: 'dabba',
  effort: 'medium',
  maxTokens: 4096,
  temperature: 0.7,
  autoReviewOnSave: false,
  enableDiagnostics: true,
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
    return {
      apiEndpoint: config.get<string>('apiEndpoint', DEFAULT_SETTINGS.apiEndpoint),
      model: config.get<string>('model', DEFAULT_SETTINGS.model),
      effort: config.get<string>('effort', DEFAULT_SETTINGS.effort),
      maxTokens: config.get<number>('maxTokens', DEFAULT_SETTINGS.maxTokens),
      temperature: config.get<number>('temperature', DEFAULT_SETTINGS.temperature),
      autoReviewOnSave: config.get<boolean>('autoReviewOnSave', DEFAULT_SETTINGS.autoReviewOnSave),
      enableDiagnostics: config.get<boolean>('enableDiagnostics', DEFAULT_SETTINGS.enableDiagnostics),
      theme: config.get<'auto' | 'light' | 'dark'>('theme', DEFAULT_SETTINGS.theme),
    };
  }

  async getApiKey(): Promise<string | undefined> {
    return this.secretStorage.get('dabba.apiKey');
  }

  async setApiKey(key: string): Promise<void> {
    await this.secretStorage.store('dabba.apiKey', key);
  }

  async clearApiKey(): Promise<void> {
    await this.secretStorage.delete('dabba.apiKey');
  }

  dispose(): void {
    this.configListener.dispose();
    this._onDidChangeSettings.dispose();
  }
}
