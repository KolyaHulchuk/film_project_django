// Shared chrome behaviour: header glass-on-scroll, sliding nav underline, expandable search, mobile drawer.
(function () {
  const header = document.querySelector('[data-site-header]');
  if (!header) return;

  const onScroll = () => header.classList.toggle('scrolled', window.scrollY > 40);
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  // sliding underline: sits under the active link, follows hover/focus, returns on leave
  const nav = header.querySelector('.nav');
  const line = header.querySelector('.nav-line');
  if (nav && line) {
    const rest = nav.querySelector('a.active');
    const moveTo = (a) => {
      if (!a || !a.offsetWidth) { line.classList.remove('ready'); return; }
      line.style.transform = 'translateX(' + (a.offsetLeft + 14) + 'px) scaleX(' + Math.max(a.offsetWidth - 28, 1) + ')';
      line.classList.add('ready');
    };
    const reset = () => moveTo(rest);
    nav.querySelectorAll('a').forEach((a) => {
      a.addEventListener('mouseenter', () => moveTo(a));
      a.addEventListener('focus', () => moveTo(a));
    });
    nav.addEventListener('mouseleave', reset);
    nav.addEventListener('focusout', reset);
    window.addEventListener('resize', reset);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(reset);
    reset();
  }

  // search bar
  const bar = header.querySelector('[data-search-bar]');
  const openSearch = header.querySelector('[data-search-open]');
  const closeSearch = header.querySelector('[data-search-close]');
  if (bar && openSearch) {
    const input = bar.querySelector('input');
    const show = () => { bar.hidden = false; input.focus(); };
    const hide = () => { bar.hidden = true; openSearch.focus(); };
    openSearch.addEventListener('click', show);
    closeSearch.addEventListener('click', hide);
    bar.addEventListener('keydown', (e) => { if (e.key === 'Escape') hide(); });

    // live suggestions: debounced fetch
    const dd = bar.querySelector('[data-search-dd]');
    const idle = bar.querySelector('[data-search-idle]');
    const live = bar.querySelector('[data-search-live]');
    const DEBOUNCE = 300, MIN_CHARS = 2;
    let debounceT, ctrl;

    const message = (text, cls) => {
      const m = document.createElement('div');
      m.className = 'sb-msg' + (cls ? ' ' + cls : '');
      m.textContent = text;
      live.replaceChildren(m);
    };
    const row = (r) => {
      const a = document.createElement('a');
      a.className = 'sr';
      a.href = r.url;
      const th = document.createElement('span');
      th.className = 'sr-th';
      if (r.poster_url) {
        const img = document.createElement('img');
        img.src = r.poster_url; img.alt = ''; img.loading = 'lazy';
        th.appendChild(img);
      }
      const b = document.createElement('div');
      b.className = 'sr-b';
      const t = document.createElement('span');
      t.className = 'sr-t'; t.textContent = r.title;
      const m = document.createElement('span');
      m.className = 'sr-m';
      m.textContent = [r.year, r.media_type === 'tv' ? 'TV' : 'Movie'].filter(Boolean).join(' · ');
      b.append(t, m);
      a.append(th, b);
      if (r.rating) {
        const rt = document.createElement('span');
        rt.className = 'sr-rate'; rt.textContent = '★ ' + r.rating;
        a.appendChild(rt);
      }
      return a;
    };
    const showLive = (on) => { live.hidden = !on; idle.hidden = on; };

    const search = async (q) => {
      if (ctrl) ctrl.abort();
      ctrl = new AbortController();
      const mine = ctrl;
      try {
        const res = await fetch(dd.dataset.suggestUrl + '?q=' + encodeURIComponent(q), { signal: mine.signal, headers: { Accept: 'application/json' } });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (mine !== ctrl) return; // a newer search took over while this one was being read
        showLive(true);
        if (!data.results.length) message('No results found');
        else live.replaceChildren(...data.results.map(row));
      } catch (err) {
        if (err.name === 'AbortError' || mine !== ctrl) return; // superseded by a newer request
        showLive(true);
        message("Couldn't load results. Please try again.", 'err');
      }
    };

    input.addEventListener('input', () => {
      clearTimeout(debounceT);
      const q = input.value.trim();
      if (q.length < MIN_CHARS) {
        if (ctrl) ctrl.abort();
        showLive(false);
        return;
      }
      debounceT = setTimeout(() => search(q), DEBOUNCE);
    });
    bar.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      const links = Array.from(live.querySelectorAll('a.sr'));
      if (!links.length) return;
      e.preventDefault();
      const i = links.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') links[Math.min(i + 1, links.length - 1)].focus();
      else if (i <= 0) input.focus();
      else links[i - 1].focus();
    });
  }

  // mobile drawer
  const drawer = document.querySelector('[data-drawer]');
  const openDrawer = header.querySelector('[data-drawer-open]');
  if (drawer && openDrawer) {
    const close = () => { drawer.hidden = true; document.body.style.overflow = ''; openDrawer.focus(); };
    openDrawer.addEventListener('click', () => { drawer.hidden = false; document.body.style.overflow = 'hidden'; });
    drawer.querySelector('[data-drawer-close]').addEventListener('click', close);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !drawer.hidden) close(); });
  }
})();
