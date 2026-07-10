import * as vscode from 'vscode';
import { SettingsManager } from './settings';

type ActionKind = 'explain' | 'refactor' | 'findBugs' | 'addComments';

export class DabbaCodeActionProvider implements vscode.CodeActionProvider {
  public static readonly providedCodeActionKinds = [
    vscode.CodeActionKind.QuickFix,
    vscode.CodeActionKind.Refactor,
    vscode.CodeActionKind.Source,
  ];

  private _disposables: vscode.Disposable[] = [];

  constructor(
    private readonly settings: SettingsManager,
    private readonly onAction: (kind: ActionKind, code: string, language: string) => void,
  ) {
    this._disposables.push(
      vscode.languages.registerCodeActionsProvider(
        { pattern: '**/*' },
        this,
        { providedCodeActionKinds: DabbaCodeActionProvider.providedCodeActionKinds },
      ),
    );
  }

  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range,
    _context: vscode.CodeActionContext,
    _token: vscode.CancellationToken,
  ): vscode.CodeAction[] {
    if (range.isEmpty) return [];

    const selectedText = document.getText(range);
    if (!selectedText.trim()) return [];

    const actions: vscode.CodeAction[] = [];

    actions.push(this._createAction(
      'Explain with dabba',
      'explain',
      '$(book)',
      selectedText,
      document.languageId,
    ));

    actions.push(this._createAction(
      'Refactor with dabba',
      'refactor',
      '$(wand)',
      selectedText,
      document.languageId,
    ));

    actions.push(this._createAction(
      'Find bugs with dabba',
      'findBugs',
      '$(bug)',
      selectedText,
      document.languageId,
    ));

    actions.push(this._createAction(
      'Add comments with dabba',
      'addComments',
      '$(comment)',
      selectedText,
      document.languageId,
    ));

    return actions;
  }

  private _createAction(
    title: string,
    kind: ActionKind,
    icon: string,
    code: string,
    language: string,
  ): vscode.CodeAction {
    const action = new vscode.CodeAction(`${icon} ${title}`, vscode.CodeActionKind.QuickFix);
    action.command = {
      command: 'dabba._executeCodeAction',
      title,
      arguments: [kind, code, language],
    };
    return action;
  }

  dispose(): void {
    this._disposables.forEach((d) => d.dispose());
  }
}
