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
