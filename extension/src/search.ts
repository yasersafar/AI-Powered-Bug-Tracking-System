// Parsing of the Search Bugs box (FR-07). Plain words are a full-text query; filters use
// `key:value` tokens, e.g.  `crash status:open severity:critical project:payments assignee:me`.

import type { BugSearch, BugStatus, Project, Severity } from "./api/types";
import { BUG_STATUSES, SEVERITIES } from "./api/types";

export const SEARCH_HELP =
  "Words search title and description. Filters: status:open|inprogress|resolved|verified|closed, " +
  "severity:critical|high|medium|low|unclassified, project:<name>, assignee:me, " +
  "reporter:me, since:YYYY-MM-DD, until:YYYY-MM-DD";

function match<T extends string>(options: readonly T[], value: string): T | undefined {
  const wanted = value.toLowerCase().replace(/[\s_-]/g, "");
  return options.find((o) => o.toLowerCase() === wanted);
}

export interface ParsedSearch {
  search: BugSearch;
  problems: string[];
}

export function parseSearch(
  text: string,
  projects: readonly Project[],
  myId?: number,
): ParsedSearch {
  const search: BugSearch = { page_size: 50 };
  const problems: string[] = [];
  const words: string[] = [];
  const statuses: BugStatus[] = [];
  const severities: Severity[] = [];
  for (const token of text.match(/"[^"]*"|\S+/g) ?? []) {
    const colon = token.indexOf(":");
    const key = colon > 0 ? token.slice(0, colon).toLowerCase() : "";
    const value = colon > 0 ? token.slice(colon + 1) : token;
    switch (key) {
      case "status": {
        const status = match(BUG_STATUSES, value);
        if (status) {
          statuses.push(status);
        } else {
          problems.push(`unknown status "${value}"`);
        }
        break;
      }
      case "severity": {
        const severity = match(SEVERITIES, value);
        if (severity) {
          severities.push(severity);
        } else {
          problems.push(`unknown severity "${value}"`);
        }
        break;
      }
      case "project": {
        const project = projects.find((p) => p.name.toLowerCase().includes(value.toLowerCase()));
        if (project) {
          search.project_id = project.id;
        } else {
          problems.push(`no project matching "${value}"`);
        }
        break;
      }
      case "assignee":
      case "reporter":
        if (value.toLowerCase() === "me" && myId !== undefined) {
          search[key === "assignee" ? "assignee_id" : "reporter_id"] = myId;
        } else {
          problems.push(`${key}: only "me" is supported`);
        }
        break;
      case "since":
      case "until":
        if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
          search[key === "since" ? "created_from" : "created_to"] =
            `${value}T${key === "since" ? "00:00:00" : "23:59:59"}Z`;
        } else {
          problems.push(`${key} needs a date like 2026-11-01`);
        }
        break;
      default:
        words.push(token);
    }
  }
  if (statuses.length) {
    search.status = statuses;
  }
  if (severities.length) {
    search.severity = severities;
  }
  const q = words.join(" ").trim();
  if (q) {
    search.q = q.slice(0, 200);
    search.sort = "relevance";
  } else {
    search.sort = "updated_desc";
  }
  return { search, problems };
}
