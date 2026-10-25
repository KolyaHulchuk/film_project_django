# Movies.hub — handoff for Claude Code

Visual front-end design (dark cinematic movie/TV site). Source of truth: the `design-source/*.dc.html` files
(also published as the "Design canvas" artifact — open it with the Artifact tool `read` action if you have the link).

## What each file is
Every `*.dc.html` is a self-contained page: `<style>` (CSS) + HTML markup + a `<script type="text/x-dc">` block (demo logic).
Syntax to translate to Django templates:
- `{{some.value}}` = a data hole  →  `{{ some.value }}`
- `<sc-for list="{{items}}" as="x">…</sc-for>`  →  `{% for x in items %}…{% endfor %}`
- `<sc-if value="{{flag}}">…</sc-if>`  →  `{% if flag %}…{% endif %}`
- `onClick="{{fn}}"`, `renderVals()`, `state` = prototype-only demo behaviour; re-implement as real views/JS.
- Files that only contain `<dc-import name="X" demo-state="…">` are just artboard wrappers (a page in one state). Ignore for production.

## Pages (main files)
| Page | File | States (wrappers) |
|---|---|---|
| Home desktop / mobile | Main.dc.html, Mobile.dc.html | — |
| Catalog | Catalog.dc.html (+Mobile) | Active, Genre, Country, Loading, Empty, Sheet |
| Profile | Profile.dc.html (+Mobile, Tablet) | Watched, Remove, Stats, Settings, Empty, Filter, Sheet |
| Detail (movie/TV) | Detail.dc.html (+Mobile, Tablet, Movie) | User, Loading, Trailer, Lightbox, NoTrailer, NoComments, Mini, Gate, UserComments, RateGuest/User/Done |
| Search (dropdown + results) | Search.dc.html | Movies, People, Mobile, Tablet, Loading, Empty, Zero, ZeroTv, Sort, Dd* (dropdown), M* (mobile overlay) |
| Auth (login, register, reset ×6) | Auth.dc.html | Login*, Register*, Reset*, NewPw*, Invalid, Done, mobile/tablet |
| Reset email template | AuthEmail.dc.html | — (table layout, inline styles) |
`canvas.json` = artboard positions/titles (design tool only).

## Design tokens (shared in every page `:root`)
bg #0A0A0B · panel #141416 · elevated #1C1C1F · line #2A2A2E · text #F5F5F6 · text2 #A1A1A8 · meta #8E8E96 · muted #6B6B73
red #E11D2E (hover #FF2E40, press #9E1220, light #FF4D5E, glow rgba(225,29,46,.35)). Font: Manrope 400–800.
Rules: red = accent only (primary buttons, focus rings, active states); ratings neutral; no green/yellow; no emoji; line icons (SVG sprite `<symbol id="i-…">`).
Motion: only transform + opacity; honour `prefers-reduced-motion`.

## Shared components (copy once into base template / static CSS)
Fixed glass header (`.hdr`, nav with sliding underline, search, Login/Register, burger+drawer), slim footer (`.foot`),
floating Cinema Assistant (`.fab` + `.chat`), buttons (`.btn-red/.btn-ghost/.btn-icon`), chips/badges, poster card (`.cc`),
round person card (`.pc`), numbered pagination (`.pg`), sort/filter popovers, skeletons (`.sk`), empty states (`.empty`),
form card (`.acard`, `.f`, `.in`, `.req` checklist, `.btn-g` Google button).
Breakpoints: 1199 / 1099 / 959 / 767 (mobile). 20 items per page everywhere.

## Backend notes
- Images: TMDB — posters w342, backdrops w780/w1280, people w185. Placeholders in the design are CSS gradients/initials.
- URLs: Catalog `?genre=&year=&country=&rating=&sort=&page=`; Search `?q=&type=all|movies|tv|people&sort=relevance|popularity|rating|newest&page=`.
- Search tabs: All · Movies · TV · People (Anime/K-Drama are labelled chips inside TV).
- Auth: Django `registration/` templates (login, register, password_reset_form/done/confirm/complete, password_reset_email.html);
  Google sign-in button uses the official multicolour "G".
- Accessibility already designed in: combobox (search), tablist, aria-live errors, aria-describedby, visible focus rings.

## Suggested prompt for Claude Code
"Read HANDOFF.md and design-source/. Build Django templates + one shared CSS file from these pages. Start with base.html
(header/footer/assistant), then Catalog, Detail, Profile, Search, Auth. Keep class names and tokens; replace demo data with real context."
