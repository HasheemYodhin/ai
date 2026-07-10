import * as vscode from 'vscode';
import { SettingsManager } from './settings';

function truncate(text: string, max: number): string {
  const oneLine = text.replace(/\s+/g, ' ').trim();
  return oneLine.length > max ? oneLine.slice(0, max - 1) + '…' : oneLine;
}

interface ReviewIssue {
  line: number;
  column?: number;
  message: string;
  severity: 'error' | 'warning' | 'info';
  suggestion?: string;
}

const SUPPORTED_LANGUAGES = [
  'javascript', 'typescript', 'python', 'java', 'go', 'rust',
  'cpp', 'c', 'csharp', 'ruby', 'php', 'swift', 'kotlin',
];

export class DabbaDiagnostics implements vscode.CodeActionProvider {
  private diagnosticCollection: vscode.DiagnosticCollection;
  private _disposables: vscode.Disposable[] = [];

  // Diagnostics alone can't carry the suggestion text back out — VS Code's
  // CodeActionProvider only hands us the vscode.Diagnostic it already knows
  // about, not the ReviewIssue that produced it. Keyed by uri.toString() so
  // provideCodeActions can look the original suggestion back up by line.
  private _issuesByUri: Map<string, ReviewIssue[]> = new Map();

  constructor(
    private readonly settings: SettingsManager,
  ) {
    this.diagnosticCollection = vscode.languages.createDiagnosticCollection('dabba');

    this._disposables.push(
      vscode.workspace.onDidSaveTextDocument(async (doc) => {
        await this._onDocumentSaved(doc);
      }),
    );

    this._disposables.push(
      vscode.commands.registerCommand('dabba.applySuggestion', async (uri: string, issue: ReviewIssue) => {
        await this._applySuggestion(uri, issue);
      }),
    );

    // Gives dabba's suggestions a real quick-fix lightbulb in the editor,
    // instead of the suggestion only being reachable by manually invoking
    // dabba.applySuggestion (which nothing else in the extension called).
    this._disposables.push(
      vscode.languages.registerCodeActionsProvider(
        SUPPORTED_LANGUAGES.map((language) => ({ language })),
        this,
        { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] },
      ),
    );
  }

  /** vscode.CodeActionProvider — surfaces a "Apply dabba's fix" quick-fix for each diagnostic that has a suggestion. */
  provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext,
  ): vscode.CodeAction[] {
    const issues = this._issuesByUri.get(document.uri.toString());
    if (!issues || issues.length === 0) { return []; }

    const actions: vscode.CodeAction[] = [];
    for (const diagnostic of context.diagnostics) {
      if (diagnostic.source !== 'dabba' || diagnostic.code !== 'dabba-suggestion') { continue; }

      const issue = issues.find((i) => Math.max(0, i.line - 1) === diagnostic.range.start.line);
      if (!issue?.suggestion) { continue; }

      const action = new vscode.CodeAction(`dabba: ${truncate(issue.suggestion, 60)}`, vscode.CodeActionKind.QuickFix);
      action.command = {
        command: 'dabba.applySuggestion',
        title: 'Apply dabba suggestion',
        arguments: [document.uri.toString(), issue],
      };
      action.diagnostics = [diagnostic];
      action.isPreferred = true;
      actions.push(action);
    }
    return actions;
  }

  private async _onDocumentSaved(document: vscode.TextDocument): Promise<void> {
    const settings = this.settings.getSettings();
    if (!settings.autoReviewOnSave || !settings.enableDiagnostics) return;

    const fileSize = document.getText().length;
    if (fileSize > 50000) return;

    const languageId = document.languageId;
    if (!SUPPORTED_LANGUAGES.includes(languageId)) return;

    try {
      const apiKey = await this.settings.getApiKey();
      const issues = await this._reviewCode(document.getText(), languageId, apiKey);
      this._updateDiagnostics(document.uri, issues);
    } catch {
      // Silently fail for auto-review to avoid annoying the user
    }
  }

  async reviewDocument(document: vscode.TextDocument): Promise<void> {
    const settings = this.settings.getSettings();
    const apiKey = await this.settings.getApiKey();

    vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification,
      title: 'dabba: Reviewing code...',
      cancellable: false,
    }, async () => {
      try {
        const issues = await this._reviewCode(document.getText(), document.languageId, apiKey);
        this._updateDiagnostics(document.uri, issues);
        if (issues.length === 0) {
          vscode.window.showInformationMessage('dabba: No issues found!');
        } else {
          vscode.window.showInformationMessage(`dabba: Found ${issues.length} potential issue(s)`);
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        vscode.window.showErrorMessage(`dabba review error: ${msg}`);
      }
    });
  }

  private async _reviewCode(
    code: string,
    language: string,
    apiKey?: string,
  ): Promise<ReviewIssue[]> {
    const settings = this.settings.getSettings();
    const endpoint = `${settings.apiEndpoint}/v1/chat/completions`;

    const prompt = `Review the following ${language} code for bugs, performance issues, security vulnerabilities, and code style problems. 

Return your response as a JSON array of objects with fields: line (number), column (optional number), message (string), severity ("error"|"warning"|"info"), and suggestion (optional string).

Only return valid JSON, no other text. If no issues found, return an empty array [].

\`\`\`${language}
${code}
\`\`\``;

    const body = {
      model: settings.model,
      messages: [
        {
          role: 'system',
          content: 'You are a code review AI. Analyze code and return issues as JSON array. Be precise and helpful.',
        },
        { role: 'user', content: prompt },
      ],
      max_tokens: 2000,
      temperature: 0.1,
      stream: false,
    };

    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`;

    const response = await fetch(endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });

    if (!response.ok) throw new Error(`API error ${response.status}`);

    const data = await response.json() as { choices?: Array<{ message?: { content?: string } }> };
    const content = data.choices?.[0]?.message?.content || '[]';

    try {
      const parsed = JSON.parse(content);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      const jsonMatch = content.match(/\[[\s\S]*\]/);
      if (jsonMatch) {
        try {
          return JSON.parse(jsonMatch[0]);
        } catch {
          return [];
        }
      }
      return [];
    }
  }

  private _updateDiagnostics(uri: vscode.Uri, issues: ReviewIssue[]): void {
    const diagnostics: vscode.Diagnostic[] = issues.map((issue) => {
      const line = Math.max(0, issue.line - 1);
      const range = new vscode.Range(
        line, issue.column ?? 0,
        line, 1000,
      );

      const severityMap: Record<string, vscode.DiagnosticSeverity> = {
        error: vscode.DiagnosticSeverity.Error,
        warning: vscode.DiagnosticSeverity.Warning,
        info: vscode.DiagnosticSeverity.Information,
      };

      const diagnostic = new vscode.Diagnostic(
        range,
        issue.message,
        severityMap[issue.severity] ?? vscode.DiagnosticSeverity.Warning,
      );
      diagnostic.source = 'dabba';

      if (issue.suggestion) {
        diagnostic.code = 'dabba-suggestion';
      }

      return diagnostic;
    });

    this.diagnosticCollection.set(uri, diagnostics);
    this._issuesByUri.set(uri.toString(), issues);
  }

  private async _applySuggestion(uri: string, issue: ReviewIssue): Promise<void> {
    if (!issue.suggestion) return;

    const editor = await vscode.window.showTextDocument(vscode.Uri.parse(uri));
    const line = Math.max(0, issue.line - 1);

    editor.edit((editBuilder) => {
      const lineText = editor.document.lineAt(line);
      editBuilder.replace(lineText.range, issue.suggestion!);
    });
  }

  clear(): void {
    this.diagnosticCollection.clear();
    this._issuesByUri.clear();
  }

  dispose(): void {
    this.diagnosticCollection.dispose();
    this._disposables.forEach((d) => d.dispose());
  }
}
