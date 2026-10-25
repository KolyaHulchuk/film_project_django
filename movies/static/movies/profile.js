// Profile / watchlist pages: sliding line under the active tab, avatar preview in the settings form.
(function () {
  const bar = document.querySelector("[data-ptabs]");
  if (bar) {
    const line = bar.querySelector(".pline");
    const place = () => {
      const active = bar.querySelector(".ptab.on");
      if (!active || !line) return;
      line.style.transform = "translateX(" + active.offsetLeft + "px) scaleX(" + active.offsetWidth + ")";
      line.classList.add("ready");
    };
    window.addEventListener("resize", place);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(place);
    place();
  }

  // Watchlist page: Watchlist / Stats tabs switch panels in place (Stats is a skeleton until aggregates exist).
  const panels = document.querySelectorAll("[data-tab-panel]");
  if (bar && panels.length) {
    const show = (name, push) => {
      panels.forEach((p) => (p.hidden = p.dataset.tabPanel !== name));
      bar.querySelectorAll("[data-ptab]").forEach((t) => {
        const on = t.dataset.ptab === name;
        t.classList.toggle("on", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      if (push) history.replaceState(null, "", name === "stats" ? "?tab=stats" : location.pathname);
      window.dispatchEvent(new Event("resize"));
    };
    bar.querySelectorAll("[data-ptab]").forEach((t) =>
      t.addEventListener("click", (e) => {
        e.preventDefault();
        show(t.dataset.ptab, true);
      })
    );
  }

  const input = document.getElementById("id_image");
  if (input) {
    const fileName = document.getElementById("fileName");
    input.addEventListener("change", () => {
      const file = input.files[0];
      if (fileName) fileName.textContent = file ? file.name : "JPG or PNG; a square photo works best.";
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        document.querySelectorAll("[data-avatar-preview]").forEach((box) => {
          let img = box.querySelector("img");
          if (!img) {
            img = document.createElement("img");
            img.alt = "";
            box.appendChild(img);
          }
          img.src = e.target.result;
        });
      };
      reader.readAsDataURL(file);
    });
  }
})();
