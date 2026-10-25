// Auth pages: show/hide password, password strength + requirement checklist, submit spinner (no double submits).
(function () {
  document.querySelectorAll("[data-eye]").forEach((btn) => {
    const input = document.getElementById(btn.dataset.eye);
    if (!input) return;
    btn.addEventListener("click", () => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  document.querySelectorAll("input[data-checklist]").forEach((input) => {
    const box = document.getElementById(input.dataset.checklist);
    if (!box) return;
    const segs = box.querySelectorAll(".str i");
    const label = box.querySelector("[data-str-label]");
    const rule = (name) => box.querySelector('[data-rule="' + name + '"]');
    function update() {
      const v = input.value;
      const hasLen = v.length >= 8;
      const nonNum = v.length > 0 && !/^\d+$/.test(v);
      const mix = /[A-Za-z]/.test(v) && /[\d\W_]/.test(v);
      [["len", hasLen], ["nonnum", nonNum], ["mix", mix]].forEach(([name, ok]) => {
        const li = rule(name);
        li.classList.toggle("ok", ok);
        li.classList.remove("bad");
      });
      let score = 0;
      if (hasLen) score++;
      if (nonNum) score++;
      if (mix) score++;
      if (v.length >= 12 && mix) score++;
      segs.forEach((s, i) => {
        s.style.transform = "scaleX(" + (i < score ? 1 : 0) + ")";
        s.style.background = score <= 1 ? "#6B6B73" : "#F5F5F6";
      });
      label.textContent = !v ? "Too short" : ["Too short", "Weak", "Okay", "Good", "Strong"][score];
    }
    input.addEventListener("input", update);
    update();
  });

  document.querySelectorAll("form[data-auth-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      const btn = form.querySelector("button[type=submit]");
      if (!btn) return;
      // Let the browser submit first, then lock the button so a double click can't send twice.
      setTimeout(() => {
        btn.setAttribute("aria-busy", "true");
        const spin = btn.querySelector(".spin");
        if (spin) spin.hidden = false;
        btn.classList.add("ld");
      }, 0);
    });
  });
  // Back/forward cache: never leave the button stuck in the loading state
  window.addEventListener("pageshow", () =>
    document.querySelectorAll("form[data-auth-form] button[type=submit]").forEach((b) => {
      b.classList.remove("ld");
      b.removeAttribute("aria-busy");
      const spin = b.querySelector(".spin");
      if (spin) spin.hidden = true;
    })
  );
})();
