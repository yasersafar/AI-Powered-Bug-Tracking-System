// Minimal stand-in for the `vscode` module so the real webview panels can render outside VS
// Code (preview and accessibility check only; see test/preview/render.ts).
import * as path from "node:path";
import { pathToFileURL } from "node:url";

export class Uri {
  private constructor(readonly fsPath: string) {}
  static file(p: string): Uri {
    return new Uri(p);
  }
  static joinPath(base: Uri, ...parts: string[]): Uri {
    return new Uri(path.join(base.fsPath, ...parts));
  }
  toString(): string {
    return pathToFileURL(this.fsPath).toString();
  }
}

export const ViewColumn = { Active: -1 };

type Listener<T> = (value: T) => void;

export class EventEmitter<T> {
  private listeners: Listener<T>[] = [];
  event = (listener: Listener<T>): { dispose: () => void } => {
    this.listeners.push(listener);
    return { dispose: () => undefined };
  };
  fire(value: T): void {
    for (const l of this.listeners) {
      l(value);
    }
  }
  dispose(): void {
    this.listeners = [];
  }
}

export interface StubPanel {
  title: string;
  html: string;
  messages: unknown[];
  send: (message: unknown) => void;
}

export const panels: StubPanel[] = [];

export const window = {
  createWebviewPanel(_type: string, title: string): object {
    const received = new EventEmitter<unknown>();
    const record: StubPanel = {
      title,
      html: "",
      messages: [],
      send: (m) => {
        received.fire(m);
      },
    };
    panels.push(record);
    const webview = {
      cspSource: "file:",
      asWebviewUri: (uri: Uri) => uri,
      onDidReceiveMessage: received.event,
      postMessage: (m: unknown) => {
        record.messages.push(m);
        return Promise.resolve(true);
      },
      set html(value: string) {
        record.html = value;
      },
      get html() {
        return record.html;
      },
    };
    return {
      webview,
      get title() {
        return record.title;
      },
      set title(v: string) {
        record.title = v;
      },
      iconPath: undefined,
      reveal: () => undefined,
      onDidDispose: () => ({ dispose: () => undefined }),
      dispose: () => undefined,
    };
  },
  showWarningMessage: () => Promise.resolve(undefined),
  showInformationMessage: () => Promise.resolve(undefined),
};

export const commands = { executeCommand: () => Promise.resolve(undefined) };
export const workspace = {};
