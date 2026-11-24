// Dependency-free SVG charts (no CDN, works under a strict CSP). Each chart is a <figure> with
// role="img", a text summary for screen readers, and the same numbers in a table (NFR-12).

import { type SafeHtml, html } from "./html";

export interface BarDatum {
  label: string;
  value: number;
}

const BAR_HEIGHT = 22;
const LABEL_WIDTH = 110;
const CHART_WIDTH = 420;

export function barChart(id: string, title: string, data: readonly BarDatum[]): SafeHtml {
  const max = Math.max(1, ...data.map((d) => d.value));
  const plot = CHART_WIDTH - LABEL_WIDTH - 50;
  const height = data.length * (BAR_HEIGHT + 6) + 6;
  const summary = data.map((d) => `${d.label} ${d.value}`).join(", ");
  return html`<figure aria-labelledby="${id}-caption">
    <figcaption id="${id}-caption"><strong>${title}</strong></figcaption>
    <svg
      class="chart"
      role="img"
      aria-label="${title}: ${summary}"
      viewBox="0 0 ${CHART_WIDTH} ${height}"
      width="${CHART_WIDTH}"
      height="${height}"
    >
      ${data.map((d, i) => {
        const y = 6 + i * (BAR_HEIGHT + 6);
        const width = Math.round((d.value / max) * plot);
        return html`<text x="0" y="${y + 15}">${d.label}</text>
          <rect
            class="bar"
            x="${LABEL_WIDTH}"
            y="${y}"
            width="${width}"
            height="${BAR_HEIGHT}"
          ></rect>
          <text x="${LABEL_WIDTH + width + 6}" y="${y + 15}">${d.value}</text>`;
      })}
    </svg>
    ${dataTable(
      title,
      ["Category", "Bugs"],
      data.map((d) => [d.label, String(d.value)]),
    )}
  </figure>`;
}

export interface SeriesPoint {
  day: string;
  created: number;
  resolved: number;
}

export function lineChart(id: string, title: string, points: readonly SeriesPoint[]): SafeHtml {
  const width = 560;
  const height = 200;
  const pad = { left: 34, right: 10, top: 10, bottom: 26 };
  const max = Math.max(1, ...points.map((p) => Math.max(p.created, p.resolved)));
  const step = points.length > 1 ? (width - pad.left - pad.right) / (points.length - 1) : 0;
  const y = (v: number): number =>
    Math.round(height - pad.bottom - (v / max) * (height - pad.top - pad.bottom));
  const line = (key: "created" | "resolved"): string =>
    points.map((p, i) => `${Math.round(pad.left + i * step)},${y(p[key])}`).join(" ");
  const created = points.reduce((a, p) => a + p.created, 0);
  const resolved = points.reduce((a, p) => a + p.resolved, 0);
  const first = points[0]?.day ?? "";
  const last = points[points.length - 1]?.day ?? "";
  return html`<figure aria-labelledby="${id}-caption">
    <figcaption id="${id}-caption">
      <strong>${title}</strong>
      <span><span class="legend-created" aria-hidden="true">■</span> created (${created})</span>
      <span><span class="legend-resolved" aria-hidden="true">■</span> resolved (${resolved})</span>
    </figcaption>
    <svg
      class="chart"
      role="img"
      aria-label="${title} from ${first} to ${last}: ${created} created, ${resolved} resolved"
      viewBox="0 0 ${width} ${height}"
      width="${width}"
      height="${height}"
    >
      <line
        class="axis"
        x1="${pad.left}"
        y1="${height - pad.bottom}"
        x2="${width - pad.right}"
        y2="${height - pad.bottom}"
      ></line>
      <line
        class="axis"
        x1="${pad.left}"
        y1="${pad.top}"
        x2="${pad.left}"
        y2="${height - pad.bottom}"
      ></line>
      <text x="0" y="${pad.top + 8}">${max}</text>
      <text x="0" y="${height - pad.bottom}">0</text>
      <text x="${pad.left}" y="${height - 6}">${first}</text>
      <text x="${width - pad.right - 70}" y="${height - 6}">${last}</text>
      <polyline
        class="line-created"
        fill="none"
        stroke-width="2"
        points="${line("created")}"
      ></polyline>
      <polyline
        class="line-resolved"
        fill="none"
        stroke-width="2"
        stroke-dasharray="5 3"
        points="${line("resolved")}"
      ></polyline>
    </svg>
    ${dataTable(
      title,
      ["Day", "Created", "Resolved"],
      points.map((p) => [p.day, String(p.created), String(p.resolved)]),
    )}
  </figure>`;
}

function dataTable(title: string, headers: string[], rows: string[][]): SafeHtml {
  return html`<details>
    <summary>Show data for “${title}”</summary>
    <table>
      <thead>
        <tr>
          ${headers.map((h) => html`<th scope="col">${h}</th>`)}
        </tr>
      </thead>
      <tbody>
        ${rows.map(
          (r) =>
            html`<tr>
              ${r.map((c) => html`<td>${c}</td>`)}
            </tr>`,
        )}
      </tbody>
    </table>
  </details>`;
}
