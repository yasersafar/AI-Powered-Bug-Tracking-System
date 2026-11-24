import { randomBytes } from "node:crypto";

// Safe HTML building for webviews: every interpolated value is escaped unless it was produced
// by `html` itself (or explicitly wrapped with `trusted`). User text can never become markup.

export class SafeHtml {
  constructor(readonly value: string) {}
  toString(): string {
    return this.value;
  }
}

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
  "`": "&#96;",
};

export function escapeHtml(value: unknown): string {
  return String(value).replace(/[&<>"'`]/g, (c) => ESCAPES[c] ?? c);
}

type Part = SafeHtml | string | number | boolean | null | undefined | readonly Part[];

function render(part: Part): string {
  if (part === null || part === undefined || part === false) {
    return "";
  }
  if (part instanceof SafeHtml) {
    return part.value;
  }
  if (Array.isArray(part)) {
    return (part as readonly Part[]).map(render).join("");
  }
  return escapeHtml(part);
}

/** Tagged template: `html\`<p>${userText}</p>\`` escapes userText. */
export function html(strings: TemplateStringsArray, ...values: Part[]): SafeHtml {
  let out = strings[0] ?? "";
  values.forEach((value, i) => {
    out += render(value) + (strings[i + 1] ?? "");
  });
  return new SafeHtml(out);
}

/** Only for markup built by this extension (never for data from the server or the user). */
export function trusted(markup: string): SafeHtml {
  return new SafeHtml(markup);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) {
    return "-";
  }
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

/** Per-render CSP nonce from the OS random generator. */
export function nonce(): string {
  return randomBytes(18).toString("base64url");
}
