// Generic webview behaviour shared by every Bug Tracker page. The page markup is rendered (and
// escaped) by the extension; this script only forwards user actions and applies updates.
//
//   <button data-action="assign" data-id="3">      -> {type: "assign", id: "3"}
//   <form data-submit="create">                    -> {type: "create", values: {...}}
//   <textarea data-debounce="checkDuplicates">     -> {type: "checkDuplicates", values} (600 ms)
//   <select data-change="selectProject">           -> {type: "selectProject", value}
//
// Messages from the extension: {type: "replace", id, html} | {type: "status", text, kind}
// | {type: "focus", id} | {type: "busy", busy}.
(function () {
  "use strict";
  const vscode = acquireVsCodeApi();
  const DEFAULT_DEBOUNCE_MS = 600;
  const timers = new Map();

  function formValues(form) {
    const values = {};
    if (!form) {
      return values;
    }
    for (const element of Array.from(form.elements)) {
      if (!element.name) {
        continue;
      }
      if (element.type === "checkbox") {
        values[element.name] = element.checked;
      } else if (element.multiple) {
        values[element.name] = Array.from(element.selectedOptions).map((o) => o.value);
      } else {
        values[element.name] = element.value;
      }
    }
    return values;
  }

  function post(type, extra) {
    vscode.postMessage(Object.assign({ type: type }, extra));
  }

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-action]") : null;
    if (!target || target.hasAttribute("disabled")) {
      return;
    }
    event.preventDefault();
    const form = target.dataset.form ? document.getElementById(target.dataset.form) : null;
    if (form && target.dataset.validate === "true" && !form.reportValidity()) {
      return;
    }
    post(target.dataset.action, Object.assign({}, target.dataset, { values: formValues(form) }));
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.dataset.submit) {
      return;
    }
    event.preventDefault();
    if (!form.reportValidity()) {
      return;
    }
    post(form.dataset.submit, { values: formValues(form) });
  });

  document.addEventListener("input", (event) => {
    const element = event.target;
    if (!(element instanceof HTMLElement) || !element.dataset.debounce) {
      return;
    }
    const type = element.dataset.debounce;
    const delay = Number(element.dataset.debounceMs || DEFAULT_DEBOUNCE_MS);
    clearTimeout(timers.get(type));
    timers.set(
      type,
      setTimeout(() => post(type, { values: formValues(element.closest("form")) }), delay),
    );
  });

  document.addEventListener("change", (event) => {
    const element = event.target;
    if (element instanceof HTMLElement && element.dataset.change) {
      post(element.dataset.change, {
        value: element.value,
        values: formValues(element.closest("form")),
      });
    }
  });

  window.addEventListener("message", (event) => {
    const message = event.data || {};
    if (message.type === "replace") {
      const element = document.getElementById(message.id);
      if (element) {
        // Markup built by the extension with every value escaped (src/webview/html.ts).
        element.innerHTML = message.html;
      }
    } else if (message.type === "status") {
      const region = document.getElementById(message.kind === "error" ? "error" : "status");
      if (region) {
        region.textContent = message.text || "";
        region.className = "notice" + (message.kind ? " " + message.kind : "");
      }
    } else if (message.type === "focus") {
      const element = document.getElementById(message.id);
      if (element) {
        element.focus();
      }
    } else if (message.type === "busy") {
      document.body.setAttribute("aria-busy", message.busy ? "true" : "false");
      for (const button of document.querySelectorAll("button[data-busy-disable]")) {
        button.disabled = Boolean(message.busy);
      }
    }
  });
})();
