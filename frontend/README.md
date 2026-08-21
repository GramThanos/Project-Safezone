# Frontend

React 18 + React Router 6 (Create React App), served by Nginx in production.

**The architecture lives in [`../AGENTS.md`](../AGENTS.md)** - which pages exist, what the admin panel is made of, how the API client is organised. This file is the part that is specific to working *in* this directory, and deliberately does not repeat the file listing: the previous version of this README did, and it described a structure that had not existed for months.

## Running it

```bash
npm install && npm start
```

Development runs on <http://localhost:3000> and proxies API calls to the backend through the `proxy` field in `package.json` (`http://backend:5000`), so requests are same-origin and there is no CORS to configure.

`REACT_APP_API_URL` is a **build-time** variable and is deliberately unset in compose: the production image talks same-origin and Nginx proxies `/api` and `/health` to the backend. Set it only when building a bundle that must point at a backend somewhere else - setting it for local work is usually a mistake.

In compose the frontend is the only service published to the host (`8080` → `80`), so it is also how you reach the backend at all.

## Conventions

- **React files are `.jsx`** - components, contexts and hooks, whether or not they contain JSX. Plain modules stay `.js`, and `src/services/api.js` is the only one.
- **All network access goes through `src/services/api.js`.** It is grouped by area (`api.auth`, `api.admin.alerts`, …) and every method takes the token explicitly rather than reading it from context, so nothing hidden decides which identity a call is made with.
- **Pages own their data.** There is no store: a page fetches what it needs on mount and holds it in `useState`. The exception is `PlayerContext`, which polls the handful of counts the navbar badges need in one place instead of every page asking for them separately.
- **No component library beyond Bootstrap.** Markup uses Bootstrap 5 classes directly.

## Theme

Two skins in one app, which is intentional: the site is a dark, game-themed page a player browses, and the admin panel is a light workbench. `AdminLayout` sets `data-bs-theme="light"` on `<html>` while it is mounted and restores the previous value on the way out, so the change reaches the footer, the scrollbars and anything Bootstrap renders outside the React tree. The change of skin is the reminder that what you click in there affects everybody.

- **Bootstrap 5.3** for layout and components, plus `public/assets/style.css` for the site's own pieces (hero masking, card banners, the `font-display` heading face).
- **Fonts**: Oswald for display headings, Roboto for body text.
- **Icons**: Bootstrap Icons (`bi bi-*`) and Font Awesome 6 (`fa-*`) are both loaded. Bootstrap Icons is what the admin panel uses.
- **Accent** is the same red as the brand; the panel keeps it for destructive and primary actions so "the red button does the thing" holds in both skins.

Bootstrap, the icon fonts and Google Fonts are loaded from CDNs in `public/index.html` with SRI hashes. A deployment that must work without outbound access from the *browser* would need those vendored.

## Building

```bash
npm run build
```

The Docker image runs this and serves the result with Nginx (`nginx.conf`), which also proxies `/api` and `/health` to the backend container. There is no server-side rendering.
