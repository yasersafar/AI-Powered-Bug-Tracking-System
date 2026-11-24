// Runs axe-core (WCAG 2.0/2.1 A and AA rules) on a preview page and prints the result into
// the page, so it can be read without any browser tooling. Preview only, never packaged.
/* global axe, document */
(async function () {
  const result = await axe.run(document.querySelector("main"), {
    runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
  });
  const out = document.createElement("pre");
  out.id = "axe-results";
  out.textContent = JSON.stringify(
    {
      violations: result.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        nodes: v.nodes.length,
        example: v.nodes[0] && v.nodes[0].html.slice(0, 160),
        why: v.nodes[0] && v.nodes[0].failureSummary,
      })),
      passes: result.passes.length,
      incomplete: result.incomplete.map((v) => v.id),
    },
    null,
    2,
  );
  document.body.appendChild(out);
})();
