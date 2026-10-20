// Reusable add/remove-watchlist toggle.
// Markup: <form method="post" action="<add url>" data-watchlist-form data-remove-url="<delete url or empty>">
//           {% csrf_token %}<button class="watchlist-btn [in-watchlist]">...</button></form>
// Delegated, so it also works for HTMX-swapped content. Forms without data-watchlist-form
// keep their normal POST + redirect + Django messages. Used by the catalog cards and the detail page.
(function () {
  const script = document.currentScript;
  const csrfToken = (script && script.dataset.csrf) || "";

  function setState(button, active) {
    button.classList.toggle("in-watchlist", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }

  function pop(button) {
    button.classList.remove("is-popping");
    void button.offsetWidth; // restart the animation
    button.classList.add("is-popping");
    button.addEventListener("animationend", () => button.classList.remove("is-popping"), { once: true });
  }

  async function send(url, method) {
    const response = await fetch(url, {
      method,
      headers: { "X-CSRFToken": csrfToken, "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
      credentials: "same-origin",
    });
    if (response.redirected) {
      // Session expired: login_required bounced us — go where the server sent us.
      window.location.href = response.url;
      return null;
    }
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }

  // Back/forward can restore a stale page (bfcache or HTTP cache) with the old button state.
  // Remember every toggle per item (keyed by the add URL) and re-apply it whenever a page is shown.
  const STORE_KEY = "watchlist-state";
  function readStore() {
    try {
      return JSON.parse(sessionStorage.getItem(STORE_KEY)) || {};
    } catch (e) {
      return {};
    }
  }
  function remember(form, state) {
    try {
      const store = readStore();
      store[form.getAttribute("action")] = state;
      sessionStorage.setItem(STORE_KEY, JSON.stringify(store));
    } catch (e) {}
  }
  function applyRemembered(root) {
    const store = readStore();
    (root || document).querySelectorAll("form[data-watchlist-form]").forEach((form) => {
      const state = store[form.getAttribute("action")];
      const button = form.querySelector(".watchlist-btn");
      if (!state || !button) return;
      setState(button, state.active);
      form.dataset.removeUrl = state.removeUrl || "";
    });
  }
  // Only for history navigation: a normal load already has fresh server-rendered state.
  window.addEventListener("pageshow", (e) => {
    const nav = performance.getEntriesByType("navigation")[0];
    if (e.persisted || (nav && nav.type === "back_forward")) applyRemembered();
  });
  document.addEventListener("htmx:afterSwap", (e) => applyRemembered(e.target));

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-watchlist-form]");
    if (!form) return;
    event.preventDefault();

    const button = form.querySelector(".watchlist-btn");
    if (!button || button.disabled) return;

    const wasActive = button.classList.contains("in-watchlist");
    const removeUrl = form.dataset.removeUrl;
    setState(button, !wasActive); // optimistic
    if (!wasActive) pop(button);
    button.disabled = true;

    try {
      let data;
      if (wasActive) {
        data = await send(removeUrl, "DELETE");
        if (data) {
          form.dataset.removeUrl = "";
          remember(form, { active: false, removeUrl: "" });
        }
      } else {
        data = await send(form.action, "POST");
        if (data) {
          form.dataset.removeUrl = data.remove_url;
          remember(form, { active: true, removeUrl: data.remove_url });
        }
      }
      if (data && !data.ok) throw new Error(data.error || "Request failed");
    } catch (err) {
      setState(button, wasActive); // revert
    } finally {
      button.disabled = false;
    }
  });
})();
