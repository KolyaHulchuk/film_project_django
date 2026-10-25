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
