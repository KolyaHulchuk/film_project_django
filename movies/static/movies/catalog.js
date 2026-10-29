// Catalog filter toolbar: popovers on desktop, bottom sheet on mobile. Markup: partials/filter_toolbar.html.
// The form is a plain GET form (genre_search / years_search / country_search / rating_search), so it also works
// without JS (the layer is just hidden); here we only open/close the panels and auto-apply on desktop.
(function () {
  const root = document.querySelector("[data-filters]");
  if (!root) return;
  const form = root.querySelector("form");
  const layer = root.querySelector("[data-layer]");
  const scrim = root.querySelector("[data-scrim]");
  const panels = layer.querySelectorAll("[data-panel]");
  const triggers = root.querySelectorAll("[data-pop]");
  const mobile = () => window.matchMedia("(max-width: 767px)").matches;
  let current = null;

  function close() {
    if (!current) return;
    layer.hidden = true;
    scrim.hidden = true;
    root.classList.remove("sheetopen");
    triggers.forEach((t) => {
      t.classList.remove("open");
      t.setAttribute("aria-expanded", "false");
    });
    current = null;
  }

  function open(key, trigger) {
    if (current === key) return close();
    close();
    current = key;
    const sheet = key === "all" || mobile();
    layer.classList.toggle("sheet", sheet);
    layer.className = layer.className.replace(/\bw-\S+/g, "").trim();
    if (!sheet) layer.classList.add("w-" + key);
    layer.classList.toggle("r", !sheet && key === "sort"); // the sort chip sits on the right edge
    if (layer.classList.contains("r")) layer.style.left = "";
    panels.forEach((p) => (p.hidden = key !== "all" && p.dataset.panel !== key));
    layer.hidden = false;
    scrim.hidden = false;
    scrim.classList.toggle("dim", sheet);
    root.classList.toggle("sheetopen", sheet);
    trigger.classList.add("open");
    trigger.setAttribute("aria-expanded", "true");
    if (!sheet && key !== "sort") {
      layer.style.left = trigger.offsetLeft + "px";
      const overflow = layer.getBoundingClientRect().right - (window.innerWidth - 16);
      if (overflow > 0) layer.style.left = Math.max(0, trigger.offsetLeft - overflow) + "px";
    }
    const focusable = layer.querySelector("[data-panel]:not([hidden]) input:not(.sr), [data-panel]:not([hidden]) label");
    if (focusable && focusable.focus) focusable.focus({ preventScroll: true });
  }

  triggers.forEach((t) => t.addEventListener("click", () => t.getAttribute("aria-disabled") !== "true" && open(t.dataset.pop, t)));
  root.querySelectorAll("[data-pop-close]").forEach((b) => b.addEventListener("click", close));
  scrim.addEventListener("click", close);
  document.addEventListener("keydown", (e) => e.key === "Escape" && close());

  const live = () => !layer.classList.contains("sheet"); // desktop popovers apply immediately, the sheet waits for "Show results"
  const apply = () => (live() ? form.requestSubmit() : refresh());

  // Keep the chips (".on" state + count bubble) in sync with the fields; the catalog renders the initial state server-side.
  const htmx = form.hasAttribute("data-htmx");
  function refresh() {
    triggers.forEach((t) => {
      const panel = layer.querySelector('[data-panel="' + t.dataset.pop + '"]');
      if (!panel || t.dataset.pop === "sort") return; // the sort chip shows its label, not a count
      const active = Array.from(panel.querySelectorAll("input[name]")).filter((el) =>
        el.type === "radio" ? el.checked : el.type === "range" ? Number(el.value) > 0 : el.value.trim() !== ""
      ).length;
      t.classList.toggle("on", active > 0);
      let n = t.querySelector(".n");
      if (active && !n) {
        n = document.createElement("span");
        n.className = "n";
        t.insertBefore(n, t.querySelector(".chev"));
      }
      if (n) active ? (n.textContent = active) : n.remove();
    });
    form.querySelectorAll("label.gchip, label.cs-row, label.so-row").forEach((l) => {
      const r = l.querySelector('input[type="radio"]');
      if (r) l.classList.toggle("on", r.checked);
    });
  }
  if (htmx) refresh();
  form.addEventListener("reset", () => setTimeout(() => { refresh(); form.requestSubmit(); if (htmx) close(); }, 0));
  form.addEventListener("submit", () => htmx && refresh());
  form.addEventListener("change", (e) => {
    const input = e.target;
    if (input.type === "radio") {
      form.querySelectorAll('input[type="radio"][name="' + input.name + '"]').forEach((r) =>
        r.closest("label").classList.toggle("on", r.checked)
      );
    }
    if (input.type === "range") {
      const out = form.querySelector("[data-rating-out]");
      out.textContent = Number(input.value) > 0 ? input.value + "+" : "Any";
    }
    apply();
  });
  form.addEventListener("input", (e) => {
    if (e.target.type === "range") {
      const out = form.querySelector("[data-rating-out]");
      out.textContent = Number(e.target.value) > 0 ? e.target.value + "+" : "Any";
      const pct = (e.target.value / e.target.max) * 100;
      e.target.style.background = "linear-gradient(90deg,var(--red) " + pct + "%,var(--line) " + pct + "%)";
    }
  });

  root.querySelectorAll("[data-clear]").forEach((btn) =>
    btn.addEventListener("click", () => {
      form.querySelectorAll('[name="' + btn.dataset.clear + '"]').forEach((el) => {
        if (el.type === "radio") {
          el.checked = false;
          el.closest("label").classList.remove("on");
        } else {
          el.value = el.type === "range" ? "0" : "";
          el.dispatchEvent(new Event("input", { bubbles: true }));
        }
      });
      apply();
    })
  );

  // Only send what is actually set: keeps the URL (and the TMDB cache key) free of empty / zero filters.
  form.addEventListener("submit", () => {
    if (htmx) return; // HTMX reads the form itself and the server ignores empty values
    form.querySelectorAll('input[type="number"], input[type="range"]').forEach((el) => {
      if (el.value === "" || (el.type === "range" && Number(el.value) === 0)) el.disabled = true;
    });
    const sort = form.querySelector('input[name="sort"][value="popularity"]');
    if (sort && sort.checked) sort.disabled = true; // the default sort stays out of the URL
  });

  if (htmx) {
    let timer;
    form.addEventListener("input", (e) => {
      if (e.target.matches('input[type="search"][name], input[type="number"]')) {
        clearTimeout(timer);
        timer = setTimeout(apply, 450);
      }
    });
    form.addEventListener("htmx:afterRequest", () => !live() && close());
  }

  const q = form.querySelector("[data-country-q]");
  const none = form.querySelector("[data-country-none]");
  if (q) {
    q.addEventListener("input", () => {
      const term = q.value.trim().toLowerCase();
      let shown = 0;
      form.querySelectorAll(".cs-row").forEach((row) => {
        const match = !term || row.dataset.name.includes(term);
        row.hidden = !match;
        if (match) shown++;
      });
      none.hidden = shown > 0;
    });
    q.addEventListener("keydown", (e) => e.key === "Enter" && e.preventDefault());
  }

  // Back/forward can restore a stale (disabled) form
  window.addEventListener("pageshow", () =>
    form.querySelectorAll("input:disabled").forEach((el) => (el.disabled = false))
  );
})();
