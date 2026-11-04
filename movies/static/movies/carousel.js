// Shared carousel arrows: any [data-row] with .track + [data-row-prev]/[data-row-next]. Used by Home and Detail.
(function () {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- Carousel arrows ----
  document.querySelectorAll("[data-row]").forEach((row) => {
    const track = row.querySelector(".track");
    const step = () => Math.max(track.clientWidth * 0.85, 200);
    const by = (dir) => track.scrollBy({ left: dir * step(), behavior: reduce ? "auto" : "smooth" });
    const prev = row.querySelector("[data-row-prev]");
    const nextB = row.querySelector("[data-row-next]");
    const sync = () => {
      const max = track.scrollWidth - track.clientWidth - 1;
      if (prev) prev.classList.toggle("is-end", track.scrollLeft <= 1);
      if (nextB) nextB.classList.toggle("is-end", track.scrollLeft >= max);
    };
    track.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    new ResizeObserver(sync).observe(track);
    sync();
    if (prev) prev.addEventListener("click", () => by(-1));
    if (nextB) nextB.addEventListener("click", () => by(1));
    track.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") by(1);
      if (e.key === "ArrowLeft") by(-1);
    });
  });
})();
