import type {
  Availability,
  DeveloperStats,
  ExperienceLevel,
  Profile,
  ProfileFields,
  Setting,
  UserSummary,
} from "../api/types";
import { type SafeHtml, formatDate, html } from "./html";
import { BasePanel, type PanelContext, type WebviewMessage, splitList, str } from "./panel";

const LEVELS: readonly ExperienceLevel[] = ["Junior", "Mid", "Senior"];
const AVAILABILITY: readonly Availability[] = ["Available", "Limited", "Unavailable"];

interface State {
  profiles: Profile[];
  settings: Setting[];
  stats: DeveloperStats[];
  candidates: UserSummary[];
}

/** FR-20 profiles, FR-21 developer tracking, NFR-14 runtime thresholds. Administrators only. */
export class AdminPanel extends BasePanel {
  private static current: AdminPanel | undefined;
  private state: State | undefined;
  private editing: number | "new" | undefined;

  static async show(ctx: PanelContext): Promise<void> {
    const panel =
      AdminPanel.current && !AdminPanel.current.isDisposed
        ? AdminPanel.current
        : new AdminPanel(ctx);
    AdminPanel.current = panel;
    panel.reveal();
    await panel.load();
  }

  private constructor(ctx: PanelContext) {
    super("bugTracker.admin", "Admin: Developers", ctx);
  }

  private async load(): Promise<void> {
    try {
      const [profiles, settings, stats, users] = await Promise.all([
        this.api.profiles(),
        this.api.settings(),
        this.api.developerStats(),
        this.api.searchUsers(""),
      ]);
      const withProfile = new Set(profiles.map((p) => p.user.id));
      this.state = {
        profiles,
        settings,
        stats,
        candidates: users.items.filter((u) => u.role === "Developer" && !withProfile.has(u.id)),
      };
      this.draw();
    } catch (error) {
      if (!this.state) {
        this.render("Administration", html`<p>Could not load the admin data.</p>`);
      }
      this.showError(error, "Loading the admin data");
    }
  }

  private draw(): void {
    const s = this.state;
    if (!s) {
      return;
    }
    this.render(
      "Administration",
      html`<nav aria-label="Sections" class="row">
          <a href="#profiles">Developer profiles</a> <a href="#stats">Developer tracking</a>
          <a href="#settings">AI thresholds</a>
        </nav>
        ${this.profiles(s)} ${this.editor(s)} ${this.stats(s.stats)} ${this.settings(s.settings)}`,
    );
  }

  private profiles(s: State): SafeHtml {
    return html`<section id="profiles" aria-labelledby="profiles-heading">
      <h2 id="profiles-heading">Developer profiles (${s.profiles.length})</h2>
      <table>
        <thead>
          <tr>
            <th scope="col">Developer</th>
            <th scope="col">Skills / components / languages</th>
            <th scope="col">Level</th>
            <th scope="col">Availability</th>
            <th scope="col">Max load</th>
            <th scope="col">Resolved</th>
            <th scope="col">Status</th>
            <th scope="col"><span class="visually-hidden">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          ${s.profiles.map(
            (p) =>
              html`<tr>
                <td>
                  ${p.user.full_name}
                  <div class="hint">${p.user.email}</div>
                </td>
                <td>
                  ${p.skills.join(", ") || "-"}
                  <div class="hint">${p.components.join(", ") || "-"}</div>
                  <div class="hint">${p.languages.join(", ") || "-"}</div>
                </td>
                <td>${p.experience_level}</td>
                <td>${p.availability}</td>
                <td>${p.max_workload}</td>
                <td>
                  ${p.resolved_count}${p.is_cold_start ? html` <span class="badge">cold start</span>` : ""}
                </td>
                <td>${p.active ? "Active" : "Deactivated"}</td>
                <td class="row">
                  <button
                    class="link"
                    data-action="edit"
                    data-id="${p.id}"
                    aria-label="Edit profile of ${p.user.full_name}"
                  >
                    Edit
                  </button>
                  <button
                    class="link"
                    data-action="toggleActive"
                    data-id="${p.id}"
                    data-active="${p.active ? "true" : "false"}"
                    aria-label="${p.active ? "Deactivate" : "Activate"} ${p.user.full_name}"
                  >
                    ${p.active ? "Deactivate" : "Activate"}
                  </button>
                </td>
              </tr>`,
          )}
        </tbody>
      </table>
      <div class="row">
        <button data-action="new" ${s.candidates.length ? "" : "disabled"}>New profile…</button>
        ${
          s.candidates.length
            ? ""
            : html`<span class="hint"
                >Every user with the Developer role already has a profile.</span
              >`
        }
      </div>
    </section>`;
  }

  private editor(s: State): SafeHtml {
    if (this.editing === undefined) {
      return html``;
    }
    const profile =
      this.editing === "new" ? undefined : s.profiles.find((p) => p.id === this.editing);
    const value = (list: string[] | undefined): string => (list ?? []).join(", ");
    return html`<section aria-labelledby="editor-heading">
      <h2 id="editor-heading">
        ${profile ? `Edit profile: ${profile.user.full_name}` : "New developer profile"}
      </h2>
      <form id="profile" data-submit="saveProfile">
        ${
          profile
            ? ""
            : html`<div class="field">
                <label for="user_id">Developer *</label>
                <select id="user_id" name="user_id" required>
                  <option value="">Choose a developer…</option>
                  ${s.candidates.map(
                    (u) => html`<option value="${u.id}">${u.full_name} (${u.email})</option>`,
                  )}
                </select>
              </div>`
        }
        <div class="field">
          <label for="skills">Skills</label>
          <input
            id="skills"
            name="skills"
            value="${value(profile?.skills)}"
            aria-describedby="list-hint"
          />
        </div>
        <div class="field">
          <label for="components">Components</label>
          <input
            id="components"
            name="components"
            value="${value(profile?.components)}"
            aria-describedby="list-hint"
          />
        </div>
        <div class="field">
          <label for="languages">Languages</label>
          <input
            id="languages"
            name="languages"
            value="${value(profile?.languages)}"
            aria-describedby="list-hint"
          />
          <span id="list-hint" class="hint">Comma separated, e.g. python, sql</span>
        </div>
        <div class="row">
          <div class="field">
            <label for="experience_level">Experience</label>
            <select id="experience_level" name="experience_level">
              ${LEVELS.map(
                (l) =>
                  html`<option ${l === (profile?.experience_level ?? "Mid") ? "selected" : ""}>
                    ${l}
                  </option>`,
              )}
            </select>
          </div>
          <div class="field">
            <label for="availability">Availability</label>
            <select id="availability" name="availability">
              ${AVAILABILITY.map(
                (a) =>
                  html`<option ${a === (profile?.availability ?? "Available") ? "selected" : ""}>
                    ${a}
                  </option>`,
              )}
            </select>
          </div>
          <div class="field">
            <label for="max_workload">Max workload</label>
            <input
              id="max_workload"
              name="max_workload"
              type="number"
              min="1"
              max="50"
              required
              value="${profile?.max_workload ?? 5}"
            />
          </div>
        </div>
        <div class="row">
          <button type="submit" data-busy-disable>Save profile</button>
          <button type="button" class="secondary" data-action="cancelEdit">Cancel</button>
        </div>
      </form>
    </section>`;
  }

  private stats(stats: DeveloperStats[]): SafeHtml {
    return html`<section id="stats" aria-labelledby="stats-heading">
      <h2 id="stats-heading">Developer tracking</h2>
      <table>
        <thead>
          <tr>
            <th scope="col">Developer</th>
            <th scope="col">Resolved</th>
            <th scope="col">Avg resolution</th>
            <th scope="col">Reassignments</th>
            <th scope="col">Workload</th>
            <th scope="col">History weight α</th>
          </tr>
        </thead>
        <tbody>
          ${stats.map(
            (d) =>
              html`<tr>
                <td>
                  ${d.user.full_name}${d.is_cold_start ? html` <span class="badge">cold start</span>` : ""}
                </td>
                <td>${d.bugs_resolved}</td>
                <td>
                  ${d.average_resolution_hours === null ? "-" : `${d.average_resolution_hours.toFixed(1)} h`}
                </td>
                <td>${d.reassignment_count}</td>
                <td>${d.current_workload}${d.max_workload ? ` / ${d.max_workload}` : ""}</td>
                <td>${d.alpha === null ? "-" : d.alpha.toFixed(2)}</td>
              </tr>`,
          )}
        </tbody>
      </table>
    </section>`;
  }

  private settings(settings: Setting[]): SafeHtml {
    return html`<section id="settings" aria-labelledby="settings-heading">
      <h2 id="settings-heading">AI thresholds and switches</h2>
      <p class="hint">Changes apply to the next request; no restart needed.</p>
      <form id="settings-form" data-submit="saveSettings">
        <table>
          <thead>
            <tr>
              <th scope="col">Setting</th>
              <th scope="col">Value</th>
              <th scope="col">Range (default)</th>
              <th scope="col">Last change</th>
            </tr>
          </thead>
          <tbody>
            ${settings.map(
              (s) =>
                html`<tr>
                  <td>
                    <label for="set-${s.key}">${s.key}</label>
                    <div id="set-${s.key}-help" class="hint">${s.description}</div>
                  </td>
                  <td>
                    <input
                      id="set-${s.key}"
                      name="${s.key}"
                      type="number"
                      min="${s.minimum}"
                      max="${s.maximum}"
                      step="${s.type === "int" ? 1 : 0.01}"
                      value="${s.value}"
                      required
                      aria-describedby="set-${s.key}-help"
                    />
                    ${s.unit}
                  </td>
                  <td>${s.minimum} – ${s.maximum} (${s.default})</td>
                  <td>
                    ${
                      s.updated_at
                        ? html`${formatDate(s.updated_at)}
                            <div class="hint">${s.updated_by?.full_name ?? ""}</div>`
                        : "default"
                    }
                  </td>
                </tr>`,
            )}
          </tbody>
        </table>
        <div class="row"><button type="submit" data-busy-disable>Save settings</button></div>
      </form>
    </section>`;
  }

  protected async onMessage(message: WebviewMessage): Promise<void> {
    switch (message.type) {
      case "new":
        this.editing = "new";
        this.draw();
        this.focus("user_id");
        return;
      case "edit":
        this.editing = Number(message.id);
        this.draw();
        this.focus("skills");
        return;
      case "cancelEdit":
        this.editing = undefined;
        this.draw();
        return;
      case "toggleActive":
        await this.save("Profile", () =>
          this.api.updateProfile(Number(message.id), { active: message.active !== "true" }),
        );
        return;
      case "saveProfile":
        await this.saveProfile(message.values);
        return;
      case "saveSettings":
        await this.saveSettings(message.values);
        return;
      default:
        return;
    }
  }

  private async saveProfile(values: Record<string, unknown> | undefined): Promise<void> {
    const fields: ProfileFields = {
      skills: splitList(str(values, "skills")),
      components: splitList(str(values, "components")),
      languages: splitList(str(values, "languages")),
      max_workload: Number(str(values, "max_workload")),
    };
    const level = LEVELS.find((l) => l === str(values, "experience_level"));
    const availability = AVAILABILITY.find((a) => a === str(values, "availability"));
    if (level) {
      fields.experience_level = level;
    }
    if (availability) {
      fields.availability = availability;
    }
    const editing = this.editing;
    await this.save("Profile", () =>
      editing === "new" || editing === undefined
        ? this.api.createProfile(Number(str(values, "user_id")), fields)
        : this.api.updateProfile(editing, fields),
    );
  }

  private async saveSettings(values: Record<string, unknown> | undefined): Promise<void> {
    const current = this.state?.settings ?? [];
    const changes: Record<string, number> = {};
    for (const s of current) {
      const value = Number(str(values, s.key));
      if (!Number.isNaN(value) && value !== s.value) {
        changes[s.key] = value;
      }
    }
    if (Object.keys(changes).length === 0) {
      this.status("No setting was changed.");
      return;
    }
    await this.save("Settings", () => this.api.updateSettings(changes));
  }

  /** Returns false when saving failed (the error is already shown in the page). */
  private async save(what: string, call: () => Promise<unknown>): Promise<boolean> {
    this.busy(true);
    this.clearMessages();
    try {
      await call();
    } catch (error) {
      this.busy(false);
      this.showError(error, `Saving ${what.toLowerCase()}`);
      return false;
    }
    if (what === "Profile") {
      this.editing = undefined;
    }
    await this.load();
    this.status(`${what} saved.`);
    this.ctx.refreshViews();
    return true;
  }

  protected override onDispose(): void {
    if (AdminPanel.current === this) {
      AdminPanel.current = undefined;
    }
  }
}
