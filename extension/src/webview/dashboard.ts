import type { Dashboard, Project } from "../api/types";
import { BUG_STATUSES, SEVERITIES } from "../api/types";
import { barChart, lineChart } from "./charts";
import { statusLabel } from "./fragments";
import { type SafeHtml, html } from "./html";
import { BasePanel, type PanelContext, type WebviewMessage } from "./panel";

/** FR-15 project dashboard. */
export class DashboardPanel extends BasePanel {
  private static current: DashboardPanel | undefined;
  private projects: Project[] = [];
  private projectId: number | undefined;
  private days = 30;

  static async show(ctx: PanelContext, projectId?: number): Promise<void> {
    const panel =
      DashboardPanel.current && !DashboardPanel.current.isDisposed
        ? DashboardPanel.current
        : new DashboardPanel(ctx);
    DashboardPanel.current = panel;
    panel.reveal();
    await panel.load(projectId);
  }

  private constructor(ctx: PanelContext) {
    super("bugTracker.dashboard", "Project Dashboard", ctx);
  }

  private async load(projectId?: number): Promise<void> {
    try {
      this.projects = await this.api.projects(true);
      this.projectId = projectId ?? this.projectId ?? this.projects[0]?.id;
      const dashboard =
        this.projectId === undefined
          ? undefined
          : await this.api.dashboard(this.projectId, this.days);
      this.draw(dashboard);
    } catch (error) {
      this.draw(undefined);
      this.showError(error, "Loading the dashboard");
    }
  }

  private draw(dashboard: Dashboard | undefined): void {
    const project = this.projects.find((p) => p.id === this.projectId);
    this.setTitle(project ? `Dashboard: ${project.name}` : "Project Dashboard");
    this.render(
      "Project dashboard",
      html`<form id="filters" class="row">
          <label for="project">Project</label>
          <select id="project" name="project" data-change="selectProject">
            ${this.projects.map(
              (p) =>
                html`<option value="${p.id}" ${p.id === this.projectId ? "selected" : ""}>
                  ${p.name}${p.is_archived ? " (archived)" : ""}
                </option>`,
            )}
          </select>
          <label for="days">Period</label>
          <select id="days" name="days" data-change="selectDays">
            ${[7, 30, 90, 365].map(
              (d) =>
                html`<option value="${d}" ${d === this.days ? "selected" : ""}>
                  Last ${d} days
                </option>`,
            )}
          </select>
          <button type="button" class="secondary" data-action="refresh">Refresh</button>
        </form>
        ${dashboard ? this.body(dashboard) : html`<p>No project to show.</p>`}`,
    );
  }

  private body(d: Dashboard): SafeHtml {
    const hours = d.average_resolution_hours;
    return html`<div class="card-grid" role="list" aria-label="Key figures">
        ${card("Total bugs", String(d.total_bugs))} ${card("Open bugs", String(d.open_bugs))}
        ${card("Open critical", String(d.open_critical))}
        ${card(
          "Average resolution",
          hours === null
            ? "-"
            : hours >= 48
              ? `${(hours / 24).toFixed(1)} days`
              : `${hours.toFixed(1)} h`,
        )}
      </div>
      <h2>By status</h2>
      ${barChart(
        "status",
        "Bugs by status",
        BUG_STATUSES.map((s) => ({ label: statusLabel(s), value: d.by_status[s] ?? 0 })),
      )}
      <h2>By severity</h2>
      ${barChart(
        "severity",
        "Bugs by severity",
        SEVERITIES.map((s) => ({ label: s, value: d.by_severity[s] ?? 0 })),
      )}
      <h2>Over time</h2>
      ${lineChart("time", `Bugs per day, last ${d.days} days`, d.over_time)}
      <h2>Components with most open bugs</h2>
      ${
        d.top_components.length
          ? html`<table>
              <thead>
                <tr>
                  <th scope="col">Component</th>
                  <th scope="col">Open bugs</th>
                </tr>
              </thead>
              <tbody>
                ${d.top_components.map(
                  (c) =>
                    html`<tr>
                      <td>${c.component}</td>
                      <td>${c.open_bugs}</td>
                    </tr>`,
                )}
              </tbody>
            </table>`
          : html`<p class="hint">No open bugs with components.</p>`
      }`;
  }

  protected async onMessage(message: WebviewMessage): Promise<void> {
    if (message.type === "selectProject") {
      await this.load(Number(message.value));
    } else if (message.type === "selectDays") {
      this.days = Number(message.value) || 30;
      await this.load(this.projectId);
    } else if (message.type === "refresh") {
      await this.load(this.projectId);
    }
  }

  protected override onDispose(): void {
    if (DashboardPanel.current === this) {
      DashboardPanel.current = undefined;
    }
  }
}

function card(label: string, value: string): SafeHtml {
  return html`<div class="card" role="listitem">
    <div class="hint">${label}</div>
    <div class="value">${value}</div>
  </div>`;
}
