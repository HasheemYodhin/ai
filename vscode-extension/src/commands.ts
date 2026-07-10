import * as vscode from 'vscode';
import { SettingsManager } from './settings';
import { InlineChat } from './inlineChat';
import { DabbaCodeActionProvider } from './codeActions';
import { DabbaDiagnostics } from './diagnostics';
import { ChatViewProvider } from './chatViewProvider';

type ActionKind = 'explain' | 'refactor' | 'findBugs' | 'addComments';

export function registerAllCommands(
  context: vscode.ExtensionContext,
  settings: SettingsManager,
  inlineChat: InlineChat,
  codeActions: DabbaCodeActionProvider,
  diagnostics: DabbaDiagnostics,
  chatProvider: ChatViewProvider,
): void {
  const openChat = vscode.commands.registerCommand('dabba.openChat', () => {
    vscode.commands.executeCommand('workbench.view.extension.dabba');
  });

  // Focus panel shortcut (Ctrl+Shift+C like Claude Code)
  const focusPanel = vscode.commands.registerCommand('dabba.focusPanel', () => {
    vscode.commands.executeCommand('dabba.chat.focus');
  });

  const newSession = vscode.commands.registerCommand('dabba.newSession', () => {
    vscode.commands.executeCommand('workbench.view.extension.dabba');
    // The webview will receive this via a postMessage after focus
  });

  const inlineChatCmd = vscode.commands.registerCommand('dabba.inlineChat', () => {
    inlineChat.activate();
  });

  const explainCode = vscode.commands.registerCommand('dabba.explainCode', async () => {
    await executeCodeAction('explain', inlineChat);
  });

  const refactorCode = vscode.commands.registerCommand('dabba.refactorCode', async () => {
    await executeCodeAction('refactor', inlineChat);
  });

  const reviewFile = vscode.commands.registerCommand('dabba.reviewFile', async () => {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
      await diagnostics.reviewDocument(editor.document);
    } else {
      vscode.window.showInformationMessage('Open a file to review.');
    }
  });

  const setApiKey = vscode.commands.registerCommand('dabba.setApiKey', async () => {
    const key = await vscode.window.showInputBox({
      prompt: 'Enter your dabba API key',
      password: true,
      ignoreFocusOut: true,
      placeHolder: 'sk-...',
      validateInput: (value) => {
        return value && value.trim().length > 0 ? null : 'API key cannot be empty';
      },
    });
    if (key) {
      await settings.setApiKey(key.trim());
      vscode.window.showInformationMessage('dabba API key saved.');
    }
  });

  const clearConversation = vscode.commands.registerCommand('dabba.clearConversation', async () => {
    // Call ChatViewProvider's own clear path directly — workbench.action.webview.sendMessage
    // targets whichever webview currently has focus, not necessarily dabba.chat, and
    // silently no-ops if the panel isn't the focused webview.
    await chatProvider.clearConversation();
    vscode.window.showInformationMessage('dabba conversation cleared.');
  });

  const executeCodeActionCmd = vscode.commands.registerCommand(
    'dabba._executeCodeAction',
    async (kind: ActionKind, code: string, language: string) => {
      const prompts: Record<ActionKind, string> = {
        explain: 'Explain the following code in detail, describing what each part does:',
        refactor: 'Refactor the following code to improve readability, performance, and maintainability:',
        findBugs: 'Analyze the following code for bugs, edge cases, and potential issues:',
        addComments: 'Add clear, concise comments to the following code explaining each section:',
      };
      const prompt = `${prompts[kind]}\n\n\`\`\`${language}\n${code}\n\`\`\``;
      await inlineChat.activateWithText(prompt, false);
    },
  );

  context.subscriptions.push(
    openChat, focusPanel, newSession, inlineChatCmd, explainCode,
    refactorCode, reviewFile, setApiKey, clearConversation, executeCodeActionCmd,
  );
}

async function executeCodeAction(kind: ActionKind, inlineChat: InlineChat): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showInformationMessage('Select code in an editor first.');
    return;
  }
  const selection = editor.selection;
  if (selection.isEmpty) {
    vscode.window.showInformationMessage('Select code to perform this action.');
    return;
  }
  const code = editor.document.getText(selection);
  const language = editor.document.languageId;
  const prompts: Record<ActionKind, string> = {
    explain: 'Explain the following code in detail:',
    refactor: 'Refactor the following code to be cleaner and more efficient:',
    findBugs: 'Analyze this code for bugs and issues:',
    addComments: 'Add comments to this code:',
  };
  const prompt = `${prompts[kind]}\n\`\`\`${language}\n${code}\n\`\`\``;
  await inlineChat.activateWithText(prompt, false);
}
