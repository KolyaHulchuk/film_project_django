// Search results: All / Movies / TV tabs (client-side, over the results already on the page) with a sliding red line.
(function () {
  const bar = document.querySelector("[data-result-tabs]");
  const grid = document.querySelector("[data-result-grid]");
  if (!bar || !grid) return;
  const tabs = Array.from(bar.querySelectorAll(".tab"));
  const line = bar.querySelector(".t-line");
  const empty = document.querySelector("[data-tab-empty]");
  const cards = Array.from(grid.querySelectorAll(".cc"));

  ["movie", "tv"].forEach((type) => {
    const n = cards.filter((c) => c.dataset.type === type).length;
    const badge = bar.querySelector('[data-count="' + type + '"]');
    if (badge) badge.textContent = n;
    const tab = bar.querySelector('[data-filter="' + type + '"]');
    if (tab) tab.classList.toggle("zero", n === 0);
  });

  function placeLine() {
    const active = bar.querySelector(".tab.on");
    if (!active || !line) return;
    line.style.transform = "translateX(" + active.offsetLeft + "px) scaleX(" + active.offsetWidth + ")";
    line.classList.add("ready");
  }
  function select(type) {
    tabs.forEach((t) => {
      const on = t.dataset.filter === type;
      t.classList.toggle("on", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    let shown = 0;
    cards.forEach((c) => {
      const show = type === "all" || c.dataset.type === type;
      c.hidden = !show;
      if (show) shown++;
    });
    grid.hidden = shown === 0;
    if (empty) empty.hidden = shown !== 0;
    placeLine();
  }
  document.querySelectorAll("[data-filter]").forEach((el) => el.addEventListener("click", () => select(el.dataset.filter)));
  window.addEventListener("resize", placeLine);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(placeLine);
  placeLine();
})();
