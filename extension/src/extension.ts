import * as vscode from 'vscode';

// Called once, the first time the user runs one of our commands.
export function activate(context: vscode.ExtensionContext) {
  const reportBug = vscode.commands.registerCommand('bugTracker.reportBug', () => {
    const panel = vscode.window.createWebviewPanel(
      'bugTracker.reportBug',
      'Report a Bug',
      vscode.ViewColumn.One,
      { enableScripts: true },
    );
    panel.webview.html = getWebviewHtml(panel.webview);

    // Messages sent from the webview with vscode.postMessage(...) arrive here.
    panel.webview.onDidReceiveMessage(
      async (message) => {
        if (message.type === 'submitBug') {
          const apiUrl = vscode.workspace.getConfiguration('bugTracker').get<string>('apiUrl');
          // TODO(#10, TheWastedArab): send message.bug to the backend, for example:
          //   const res = await fetch(`${apiUrl}/bugs`, { method: 'POST',
          //     headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(message.bug) });
          //   const saved = await res.json();
          //   panel.webview.postMessage({ type: 'bugSaved', bug: saved });
          // Show saved.severity to the user. Show an error message if the backend is not running.
          vscode.window.showInformationMessage(`TODO(#10): send the bug to ${apiUrl}/bugs`);
        }
      },
      undefined,
      context.subscriptions,
    );
  });

  context.subscriptions.push(reportBug);
}

export function deactivate() {}

function getWebviewHtml(webview: vscode.Webview): string {
  const nonce = getNonce();
  // TODO(#10, TheWastedArab): replace the placeholder with the real bug form
  //   (title, description, ...). On submit, call:
  //   vscode.postMessage({ type: 'submitBug', bug: { title, description } });
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Report a Bug</title>
</head>
<body>
  <h1>Report a Bug</h1>
  <p>The bug form will go here (issue #10).</p>
  <button id="test">Send a test bug</button>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    document.getElementById('test').addEventListener('click', () => {
      vscode.postMessage({ type: 'submitBug', bug: { title: 'Test bug', description: 'Sent from the skeleton' } });
    });
  </script>
</body>
</html>`;
}

function getNonce(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let nonce = '';
  for (let i = 0; i < 32; i++) {
    nonce += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return nonce;
}
