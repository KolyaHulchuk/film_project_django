// Home page behaviour: hero carousel, carousel arrows, "Popular Right Now" tabs. Markup: movies/home.html.
(function () {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- Hero carousel (autoplay 7s, pauses on hover/focus/hidden tab; no autoplay with reduced motion) ----
  const hero = document.querySelector("[data-hero]");
  if (hero) {
    const bgs = hero.querySelectorAll("[data-hero-bg]");
    const copies = hero.querySelectorAll("[data-hero-copy]");
    const segs = hero.querySelectorAll("[data-hero-seg]");
    const counter = hero.querySelector("[data-hero-counter]");
    const total = bgs.length;
    let index = 0;
    let timer = null;
    const pad = (n) => String(n).padStart(2, "0");

    let show = function (i) {
      index = (i + total) % total;
      bgs.forEach((el, n) => {
        el.classList.toggle("on", n === index);
        el.classList.toggle("kb", n === index && !reduce);
      });
      copies.forEach((el, n) => (el.hidden = n !== index));
      segs.forEach((el, n) => {
        const fill = el.querySelector(".seg-fill");
        el.toggleAttribute("aria-current", n === index);
        fill.classList.remove("run", "done");
        void fill.offsetWidth; // restart the CSS animation
        if (n < index) fill.classList.add("done");
        else if (n === index && !reduce && timer !== "paused") fill.classList.add("run");
      });
      if (counter) counter.textContent = pad(index + 1) + " / " + pad(total);
    };
    const next = () => show(index + 1);

    function schedule() {
      clearTimeout(timer);
      if (reduce || total < 2) return;
      timer = setTimeout(next, 7000);
    }
    function go(i) {
      show(i);
      schedule();
    }
    segs.forEach((el, n) => el.addEventListener("click", () => go(n)));
    const prevBtn = hero.querySelector("[data-hero-prev]");
    const nextBtn = hero.querySelector("[data-hero-next]");
    if (prevBtn) prevBtn.addEventListener("click", () => go(index - 1));
    if (nextBtn) nextBtn.addEventListener("click", () => go(index + 1));
    // copy fade-up only plays on first paint; re-trigger on slide change
    const restartCopy = () => copies[index].querySelectorAll(".fu").forEach((el) => {
      el.style.animation = "none";
      void el.offsetWidth;
      el.style.animation = "";
    });
    const _show = show;
    show = function (i) {
      _show(i);
      restartCopy();
    };
    hero.addEventListener("mouseenter", () => clearTimeout(timer));
    hero.addEventListener("mouseleave", schedule);
    hero.addEventListener("focusin", () => clearTimeout(timer));
    hero.addEventListener("focusout", schedule);
    document.addEventListener("visibilitychange", () => (document.hidden ? clearTimeout(timer) : schedule()));
    segs.length && segs[0].querySelector(".seg-fill").classList.add(reduce ? "done" : "run");
    schedule();
  }

  // ---- Carousel arrows ----
  document.querySelectorAll("[data-row]").forEach((row) => {
    const track = row.querySelector(".track");
    const step = () => Math.max(track.clientWidth * 0.85, 200);
    const by = (dir) => track.scrollBy({ left: dir * step(), behavior: reduce ? "auto" : "smooth" });
    const prev = row.querySelector("[data-row-prev]");
    const nextB = row.querySelector("[data-row-next]");
    if (prev) prev.addEventListener("click", () => by(-1));
    if (nextB) nextB.addEventListener("click", () => by(1));
    track.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") by(1);
      if (e.key === "ArrowLeft") by(-1);
    });
  });

  // ---- Tabs with the sliding red line (Popular Right Now) ----
  document.querySelectorAll("[data-tabs]").forEach((group) => {
    const panel = document.querySelector('[data-tab-panel="' + group.dataset.tabs + '"]');
    const line = group.querySelector(".ptab-line");
    const tabs = group.querySelectorAll("[data-tab]");
    function moveLine() {
      const active = group.querySelector(".ptab.on");
      if (!active || !line) return;
      line.style.transform = "translateX(" + active.offsetLeft + "px) scaleX(" + active.offsetWidth + ")";
    }
    function select(kind) {
      tabs.forEach((t) => {
        const on = t.dataset.tab === kind;
        t.classList.toggle("on", on);
        t.setAttribute("aria-pressed", on ? "true" : "false");
      });
      if (panel) {
        panel.querySelectorAll("[data-kind]").forEach((el) => (el.hidden = kind !== "all" && el.dataset.kind !== kind));
        panel.scrollTo({ left: 0 });
      }
      moveLine();
    }
    tabs.forEach((t) => t.addEventListener("click", () => select(t.dataset.tab)));
    window.addEventListener("resize", moveLine);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(moveLine);
    moveLine();
  });
})();
