import * as vscode from 'vscode';
import { SettingsManager } from './settings';

export class InlineChat {
  private panel: vscode.WebviewPanel | undefined;

  constructor(private readonly settings: SettingsManager) {}

  async activate(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showInformationMessage('Open a file to use inline chat.');
      return;
    }

    const selection = editor.selection;
    const selectedText = editor.document.getText(selection);
    const hasSelection = !selection.isEmpty;

    const input = await vscode.window.showInputBox({
      prompt: hasSelection ? 'Ask about the selected code:' : 'Ask dabba about your code:',
      placeHolder: 'e.g., Explain this code, find bugs, refactor...',
      value: hasSelection ? 'Explain this code: ' : '',
      ignoreFocusOut: true,
    });

    if (input === undefined) return;

    const prompt = hasSelection
      ? `${input}\n\n\`\`\`${editor.document.languageId}\n${selectedText}\n\`\`\``
      : input;

    await this._showResponse(prompt, editor.document);
  }

  async activateWithText(text: string, appendSelection: boolean = true): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;

    const selection = editor.selection;
    const selectedText = editor.document.getText(selection);

    const prompt = (appendSelection && selectedText)
      ? `${text}\n\n\`\`\`${editor.document.languageId}\n${selectedText}\n\`\`\``
      : text;

    await this._showResponse(prompt, editor.document);
  }

  private async _showResponse(prompt: string, document: vscode.TextDocument): Promise<void> {
    const settings = this.settings.getSettings();
    const apiKey = await this.settings.getApiKey();

    try {
      const response = await this._queryInline(prompt, settings, apiKey);
      await this._showResultPanel(response, document.languageId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      vscode.window.showErrorMessage(`dabba inline chat error: ${msg}`);
    }
  }

  private async _queryInline(
    prompt: string,
    settings: ReturnType<SettingsManager['getSettings']>,
    apiKey: string | undefined,
  ): Promise<string> {
    const endpoint = `${settings.apiEndpoint}/v1/chat/completions`;

    const body = {
      model: settings.model,
      messages: [
        {
          role: 'system',
          content: 'You are dabba, an AI coding assistant integrated into VS Code. Provide concise, accurate code explanations and suggestions. When providing code, include the code block with language identifier.',
        },
        { role: 'user', content: prompt },
      ],
      max_tokens: settings.maxTokens,
      temperature: settings.temperature,
      stream: false,
    };

    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`;

    const response = await fetch(endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`API error ${response.status}: ${errText}`);
    }

    const data = await response.json() as { choices?: Array<{ message?: { content?: string } }> };
    return data.choices?.[0]?.message?.content || 'No response generated.';
  }

  private async _insertCodeAtCursor(code: string): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
      editor.edit((editBuilder) => {
        editBuilder.insert(editor.selection.active, code);
      });
    }
  }

  private async _showResultPanel(content: string, languageId: string): Promise<void> {
    const editor = vscode.window.activeTextEditor;

    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside);
    } else {
      this.panel = vscode.window.createWebviewPanel(
        'dabba.inlineResult',
        'dabba AI Response',
        vscode.ViewColumn.Beside,
        { enableScripts: true, retainContextWhenHidden: true },
      );
      this.panel.onDidDispose(() => { this.panel = undefined; });

      this.panel.webview.onDidReceiveMessage(async (message) => {
        switch (message.type) {
          case 'insertCode':
            await this._insertCodeAtCursor(message.code);
            break;
        }
      });
    }

    const insertableContent = content
      .replace(/```[\w]*\n?/g, '')
      .replace(/```/g, '')
      .trim();

    const styledContent = content
      .replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        const langLabel = lang || languageId;
        const escaped = code
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
        return `<pre><code class="language-${langLabel}">${escaped}</code></pre>`;
      })
      .replace(/\n/g, '<br>');

    this.panel.webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
  <style>
    body { font-family: var(--vscode-font-family); padding: 16px; color: var(--vscode-editor-foreground); background: var(--vscode-editor-background); }
    .content { line-height: 1.6; white-space: pre-wrap; }
    pre { background: var(--vscode-textCodeBlock-background); padding: 12px; border-radius: 4px; overflow-x: auto; }
    code { font-family: var(--vscode-editor-font-family); font-size: var(--vscode-editor-font-size); }
    .actions { margin-top: 16px; display: flex; gap: 8px; }
    button { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; padding: 6px 14px; cursor: pointer; border-radius: 3px; }
    button:hover { background: var(--vscode-button-hoverBackground); }
  </style>
</head>
<body>
  <div class="content">${styledContent}</div>
  <div class="actions">
    <button onclick="copyCode()">Copy Code</button>
    <button onclick="insertCode()">Insert at Cursor</button>
  </div>
  <script>
    const code = ${JSON.stringify(insertableContent)};
    function copyCode() {
      navigator.clipboard.writeText(code).then(() => {
        document.querySelector('button').textContent = 'Copied!';
      });
    }
    function insertCode() {
      const vscode = acquireVsCodeApi();
      vscode.postMessage({ type: 'insertCode', code });
    }
  </script>
</body>
</html>`;
  }
}
