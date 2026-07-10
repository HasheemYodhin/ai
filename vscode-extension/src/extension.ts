import * as vscode from 'vscode';
import { SettingsManager } from './settings';
import { ChatViewProvider } from './chatViewProvider';
import { InlineChat } from './inlineChat';
import { DabbaCodeActionProvider } from './codeActions';
import { DabbaDiagnostics } from './diagnostics';
import { registerAllCommands } from './commands';

let statusBarItem: vscode.StatusBarItem;
let activeChatProvider: ChatViewProvider | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const settings = new SettingsManager(context);

  const chatProvider = new ChatViewProvider(context.extensionUri, settings, context);
  activeChatProvider = chatProvider;

  const inlineChat = new InlineChat(settings);

  const codeActions = new DabbaCodeActionProvider(settings, async (kind, code, language) => {
    const prompts: Record<string, string> = {
      explain: 'Explain the following code in detail:',
      refactor: 'Refactor the following code:',
      findBugs: 'Find bugs in this code:',
      addComments: 'Add comments to this code:',
    };
    const prompt = `${prompts[kind]}\n\`\`\`${language}\n${code}\n\`\`\``;
    await inlineChat.activateWithText(prompt);
  });


  const diagnostics = new DabbaDiagnostics(settings);

  registerAllCommands(context, settings, inlineChat, codeActions, diagnostics, chatProvider);

  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.text = '$(comment-discussion) dabba';
  statusBarItem.tooltip = 'Open dabba AI Chat';
  statusBarItem.command = 'dabba.openChat';
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, chatProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
  );

  context.subscriptions.push(settings, codeActions, diagnostics);

  vscode.window.onDidChangeActiveTextEditor((editor) => {
    if (editor) {
      statusBarItem.show();
    }
  });

  _showStartupMessage(context);
}

export async function deactivate(): Promise<void> {
  // context.subscriptions handles disposing settings/codeActions/diagnostics
  // and the webview provider registration itself; this covers what those
  // don't — an in-flight agent request and any tool calls still awaiting
  // approval, both of which would otherwise be orphaned server-side.
  await activeChatProvider?.dispose();
  activeChatProvider = undefined;
}

function _showStartupMessage(context: vscode.ExtensionContext): void {
  const key = 'dabba.hasShownWelcome';
  if (!context.globalState.get<boolean>(key)) {
    const show = 'Open Chat';
    const setup = 'Set API Key';
    vscode.window.showInformationMessage(
      'dabba AI is ready! Chat with dabba to get code assistance.',
      show,
      setup,
    ).then((selection) => {
      if (selection === show) {
        vscode.commands.executeCommand('dabba.openChat');
      } else if (selection === setup) {
        vscode.commands.executeCommand('dabba.setApiKey');
      }
    });
    context.globalState.update(key, true);
  }
}
