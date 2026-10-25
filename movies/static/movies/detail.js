// Detail page behaviour: synopsis clamp toggle, sub-nav scroll-spy + mini bar, trailer modal/inline player,
// stills lightbox, cast arrows, copy link. Markup: movies/movies_detail.html.
(function () {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  // ---- Synopsis: only offer "Read more" when the 3-line clamp actually hides text ----
  const syn = $("[data-syn]");
  const synBtn = $("[data-syn-toggle]");
  if (syn && synBtn) {
    const check = () => {
      if (syn.classList.contains("open")) return;
      synBtn.hidden = syn.scrollHeight <= syn.clientHeight + 1;
    };
    synBtn.addEventListener("click", () => {
      const open = syn.classList.toggle("open");
      synBtn.textContent = open ? "Show less" : "Read more";
      synBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    window.addEventListener("resize", check);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(check);
    check();
  }

  // ---- Sub-nav: scroll-spy, sliding line, mini bar ----
  const snav = $("[data-snav]");
  if (snav) {
    const tabs = $$(".stab", snav);
    const line = $(".sline", snav);
    const mini = $("[data-mini]", snav);
    const hero = $("#hero");
    const sections = tabs.map((t) => document.getElementById(t.dataset.target)).filter(Boolean);
    function moveLine() {
      const active = $(".stab.on", snav);
      if (!active || !line) return;
      line.style.transform = "translateX(" + active.offsetLeft + "px) scaleX(" + active.offsetWidth + ")";
      line.classList.add("ready");
    }
    function spy() {
      const y = window.scrollY + 160;
      let current = sections[0];
      sections.forEach((s) => {
        if (s.getBoundingClientRect().top + window.scrollY <= y) current = s;
      });
      tabs.forEach((t) => {
        const on = current && t.dataset.target === current.id;
        t.classList.toggle("on", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      moveLine();
      if (mini && hero) {
        const shown = hero.getBoundingClientRect().bottom < 60;
        mini.classList.toggle("show", shown);
        mini.setAttribute("aria-hidden", shown ? "false" : "true");
        $$("button", mini).forEach((b) => (b.tabIndex = shown ? 0 : -1));
      }
    }
    let ticking = false;
    window.addEventListener("scroll", () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        spy();
        ticking = false;
      });
    }, { passive: true });
    window.addEventListener("resize", spy);
    tabs.forEach((t) =>
      t.addEventListener("click", (e) => {
        const target = document.getElementById(t.dataset.target);
        if (!target) return;
        e.preventDefault();
        target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
        history.replaceState(null, "", "#" + target.id);
      })
    );
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(spy);
    spy();

    // mini-bar watchlist button mirrors and triggers the main one
    const main = $("[data-wl-main]");
    const proxy = $("[data-wl-proxy]", snav);
    if (main && proxy) {
      const text = $("[data-wl-proxy-text]", proxy);
      const sync = () => {
        const on = main.classList.contains("in-watchlist");
        proxy.classList.toggle("inwl", on);
        text.textContent = on ? "In Watchlist" : "Add to Watchlist";
      };
      new MutationObserver(sync).observe(main, { attributes: true, attributeFilter: ["class"] });
      proxy.addEventListener("click", () => main.click());
      sync();
    }
  }

  // ---- Trailer (YouTube embed is created only on click; same sandbox rules as before) ----
  function embed(key, title) {
    const f = document.createElement("iframe");
    f.src = "https://www.youtube.com/embed/" + encodeURIComponent(key) + "?playsinline=1&rel=0&modestbranding=1&autoplay=1";
    f.title = title || "Trailer";
    f.referrerPolicy = "strict-origin-when-cross-origin";
    f.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
    f.setAttribute("sandbox", "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-presentation");
    f.allowFullscreen = true;
    return f;
  }
  const tm = $("[data-tm]");
  let lastFocus = null;
  function closeTrailer() {
    if (!tm || tm.hidden) return;
    $("[data-tm-body]", tm).replaceChildren();
    tm.hidden = true;
    document.body.style.overflow = "";
    if (lastFocus) lastFocus.focus();
  }
  $$("[data-trailer-open]").forEach((btn) =>
    btn.addEventListener("click", () => {
      lastFocus = btn;
      $("[data-tm-body]", tm).replaceChildren(embed(btn.dataset.trailerOpen, btn.dataset.trailerTitle));
      tm.hidden = false;
      document.body.style.overflow = "hidden";
      $("[data-tm-close]", tm).focus();
    })
  );
  $$("[data-trailer-inline]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const box = btn.closest(".trailer");
      box.replaceChildren(embed(btn.dataset.trailerInline, btn.dataset.trailerTitle));
    })
  );
  if (tm) {
    $("[data-tm-close]", tm).addEventListener("click", closeTrailer);
    tm.addEventListener("click", (e) => e.target === tm && closeTrailer());
  }

  // ---- Stills lightbox ----
  const lb = $("[data-lb-root]");
  const thumbs = $$("[data-lb]");
  if (lb && thumbs.length) {
    const img = $("[data-lb-img]", lb);
    const count = $("[data-lb-count]", lb);
    let idx = 0;
    const show = (i) => {
      idx = (i + thumbs.length) % thumbs.length;
      img.src = thumbs[idx].href;
      img.alt = $("img", thumbs[idx]).alt;
      count.textContent = idx + 1 + " / " + thumbs.length;
    };
    const close = () => {
      lb.hidden = true;
      document.body.style.overflow = "";
    };
    thumbs.forEach((a, i) =>
      a.addEventListener("click", (e) => {
        e.preventDefault();
        lastFocus = a;
        show(i);
        lb.hidden = false;
        document.body.style.overflow = "hidden";
        $("[data-lb-close]", lb).focus();
      })
    );
    $("[data-lb-close]", lb).addEventListener("click", () => {
      close();
      if (lastFocus) lastFocus.focus();
    });
    $("[data-lb-prev]", lb).addEventListener("click", () => show(idx - 1));
    $("[data-lb-next]", lb).addEventListener("click", () => show(idx + 1));
    document.addEventListener("keydown", (e) => {
      if (lb.hidden) return;
      if (e.key === "ArrowLeft") show(idx - 1);
      if (e.key === "ArrowRight") show(idx + 1);
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    closeTrailer();
    if (lb && !lb.hidden) {
      lb.hidden = true;
      document.body.style.overflow = "";
    }
  });

  // ---- Media tabs (Stills real, Posters is a skeleton until TMDB posters are wired) ----
  document.querySelectorAll("[data-media-tabs]").forEach((group) => {
    group.querySelectorAll("[data-media-tab]").forEach((tab) =>
      tab.addEventListener("click", () => {
        const which = tab.dataset.mediaTab;
        document.querySelectorAll("[data-media-tab]").forEach((t) => {
          const on = t.dataset.mediaTab === which;
          t.classList.toggle("on", on);
          t.setAttribute("aria-selected", on ? "true" : "false");
        });
        document.querySelectorAll("[data-media-panel]").forEach((p) => (p.hidden = p.dataset.mediaPanel !== which));
      })
    );
  });

  // ---- Cast arrows ----
  const track = $("[data-cast-track]");
  if (track) {
    const by = (dir) => track.scrollBy({ left: dir * Math.max(track.clientWidth * 0.8, 200), behavior: reduce ? "auto" : "smooth" });
    const prev = $("[data-cast-prev]");
    const next = $("[data-cast-next]");
    if (prev) prev.addEventListener("click", () => by(-1));
    if (next) next.addEventListener("click", () => by(1));
  }

  // ---- Copy link ----
  const copy = $("[data-copy-link]");
  if (copy) {
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(location.href.split("#")[0]);
        copy.setAttribute("title", "Link copied");
        copy.setAttribute("aria-label", "Link copied");
        setTimeout(() => {
          copy.setAttribute("title", "Copy link");
          copy.setAttribute("aria-label", "Copy link");
        }, 2000);
      } catch (e) {
        window.prompt("Copy this link:", location.href.split("#")[0]);
      }
    });
  }
})();
