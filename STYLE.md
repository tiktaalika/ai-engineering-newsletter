# Design & Style Guide: AI Engineering Newsletter

This style guide documents the editorial, paper-like design system of the **AI Engineering Newsletter**. It provides design tokens, layout structures, and reusable component definitions to recreate the site's layout and aesthetic from scratch.

---

## 1. Design Tokens

### Color Palette
The site uses a warm, editorial, book-like color scheme that emphasizes readability and structured data hierarchy.

```css
:root {
  color-scheme: light;
  --ink: #191815;        /* Primary text, active states, heavy borders */
  --muted: #6f6a60;      /* Subtitles, secondary text, metadata, details */
  --line: #d7d0c2;       /* Subtle separators, borders, dividers */
  --paper: #f8f5ee;      /* Soft backdrop underlay, frosted blur base */
  --panel: #fffdf8;      /* Primary container backgrounds (cards, reports) */
  --accent: #0b6b5a;     /* Branding forest teal (ranks, code highlights) */
  --accent-2: #c1492e;   /* Brick terracotta red (eyebrows, notifications) */
  --shadow: 0 22px 70px rgba(47, 38, 24, .11); /* Soft warm card drop shadow */
}
```

### Typography
The typography uses a classic pairing of high-legibility Serif for body reading and structured Sans-Serif for interface meta-text, numbers, and tags.

| Font Role | Font Stack | Usage |
| :--- | :--- | :--- |
| **Primary Serif** | `Charter`, `"Iowan Old Style"`, `Georgia`, `serif` | Body text, summaries, article/page titles (`h1`, `h2`, `.zh-summary`, `.en-summary`) |
| **Secondary Sans-Serif** | `"Avenir Next"`, `Verdana`, `sans-serif` | Meta tags, dates, audit logs, rank numbers, action items (`.eyebrow`, `.rank`, `.meta`, `.audit`) |

### Background Canvas
The background features a two-tiered layer: a fine grid-line canvas superimposed on a vertical gradient.

```css
body {
  margin: 0;
  font-family: Charter, "Iowan Old Style", Georgia, serif;
  background:
    linear-gradient(90deg, rgba(25, 24, 21, .035) 1px, transparent 1px) 0 0/38px 38px,
    linear-gradient(#fbf8f1, #eee7d8);
  color: var(--ink);
}
```

### Layout Grid & Spacing
- **Container Shell (`.shell`)**: Max width of `1180px` for main contents, centered with `margin: 0 auto`. Padding is `34px 22px 80px`.
- **Landing Panel (`.landing-panel`)**: Max width of `980px` for high-impact home page layout.
- **Breakpoints**: 
  - Mobile layout transitions at **`860px`** and below.

---

## 2. Layout Patterns

### A. Sticky Frosted Header (`.hero`)
A sticky navigation bar that blurs the underlying content as you scroll.
- **Backdrop Blur**: `backdrop-filter: blur(18px)`.
- **Background**: Semi-transparent cream blended via `color-mix(in srgb, var(--paper) 78%, transparent)`.
- **Border**: Thin line `1px solid rgba(25,24,21,.1)`.

```html
<header class="hero">
  <div class="hero-inner">
    <div>
      <h1>AI Engineering Newsletter</h1>
      <p class="subtitle">Bilingual daily news push and GitHub Trend monitor.</p>
    </div>
    <div class="stamp">Latest Issued<br><strong>2026-07-31</strong></div>
  </div>
</header>
```

### B. Newsletter Split Column (`.columns`)
For daily editions, the content uses an asymmetric 2-column layout:
- **Left Column** (`1.25fr`): General AI News (occupies more horizontal room).
- **Right Column** (`0.85fr`): Sidebar containing Engineering AI and Biomedical AI sections.

```css
.columns {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(300px, .85fr);
  gap: 24px;
}
```

---

## 3. Reusable UI Components

### A. Navigation & Link Buttons (`.nav`, `.pager`, `.language-switch`)
Used for tabs, pagination, and language switching. They consist of boxy, semi-transparent elements that shift style dynamically.

```css
.nav a, .nav span, .language-switch a, .pager a, .pager span {
  color: var(--ink);
  border: 1px solid var(--line);
  padding: 7px 10px;
  text-decoration: none;
  background: rgba(255, 255, 255, .55);
}
.language-switch a.active {
  background: var(--ink);
  color: var(--panel);
  border-color: var(--ink);
}
```

### B. Issue Panel (`.day`)
A self-contained card container for a daily digest.

```css
.day {
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  margin: 28px 0;
  padding: 24px;
}
/* For scheduled dates that have no compiled articles: */
.day.missing {
  border-style: dashed;
}
```

### C. News Item Card (`.item`)
Cards for individual news items, utilizing grid layout to align index ranks.

```html
<article class="item">
  <div class="rank">01</div>
  <div>
    <p class="zh-summary">中文简短导读摘要，加粗展示以提高可读性。</p>
    <h4><a href="https://example.com/news">Example News Article Title</a></h4>
    <div class="meta">
      <span>TechCrunch</span>
      <span>score 85</span>
    </div>
    <p class="reason">High citation volume; first release by original author.</p>
  </div>
</article>
```

```css
.item {
  display: grid;
  grid-template-columns: 42px 1fr;
  gap: 12px;
  padding: 15px 0;
  border-top: 1px solid var(--line);
}
.rank {
  font-family: "Avenir Next", Verdana, sans-serif;
  color: var(--accent);
  font-weight: 700;
}
.zh-summary {
  margin: 0 0 7px;
  font-size: 18px;
  line-height: 1.38;
  font-weight: 700;
  color: var(--ink);
}
.en-summary {
  margin: 8px 0 0;
  font-size: 15px;
  line-height: 1.46;
  color: var(--muted);
}
.reason {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.4;
}
```

### D. Paper Push Block (`.paper-push`)
Special layout styling applied to weekly curated academic literature reviews. It is marked with heavy top divider lines.

```css
.paper-push {
  margin-top: 26px;
  padding-top: 20px;
  border-top: 2px solid var(--ink);
}
.paper-intro {
  margin: 0 0 8px;
  color: var(--muted);
  line-height: 1.5;
  max-width: 820px;
}
.paper-item {
  display: grid;
  grid-template-columns: 42px 1fr;
  gap: 12px;
  padding: 15px 0;
  border-top: 1px solid var(--line);
}
```

### E. GitHub Trend Panel (`.trend-panel`)
A stark, high-contrast dark card section utilized on the landing page to break layout repetition and highlight data monitoring.

```css
.trend-panel {
  background: var(--ink);
  color: var(--panel);
  margin: 0 0 28px;
  padding: 24px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, .8fr);
  gap: 24px;
  align-items: end;
}
.trend-panel .eyebrow {
  color: #f0b45f; /* Specific yellow accent for dark container eyebrows */
}
.trend-panel h2 {
  font-size: 32px;
}
.trend-panel p {
  margin: 10px 0 0;
  color: rgba(255, 253, 248, .76);
  line-height: 1.5;
  max-width: 720px;
}
.trend-actions a {
  border: 1px solid rgba(255, 253, 248, .28);
  color: var(--panel);
  padding: 14px;
  text-decoration: none;
  background: rgba(255, 253, 248, .08);
}
```

### F. Trend Reports (`.report-document` & `.report-table`)
The dashboard structure for weekly and monthly reports, generated from markdown files.

```css
.report-document {
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  padding: 24px;
}
.report-document h1 {
  font-size: 40px;
  margin-bottom: 14px;
}
.report-document h2 {
  border-top: 2px solid var(--ink);
  margin-top: 30px;
  padding-top: 18px;
  font-size: 28px;
}
.report-document p, .report-document li {
  line-height: 1.5;
  color: var(--muted);
}
/* Horizontal scrolling container wrapper for markdown tables on smaller viewports */
.report-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  margin: 14px 0 22px;
}
.report-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 980px;
  font-family: "Avenir Next", Verdana, sans-serif;
  font-size: 12px;
}
.report-table th, .report-table td {
  border-bottom: 1px solid var(--line);
  padding: 8px;
  text-align: left;
  vertical-align: top;
}
.report-table th {
  background: #eee7d8;
  color: var(--ink);
  position: sticky;
  top: 0;
}
code {
  background: rgba(11, 107, 90, .08); /* Transparent accent background for tags */
  padding: 1px 4px;
}
```

---

## 4. Mobile Responsiveness (Media Queries)
For screens smaller than **`860px`**, grid systems collapse into a single-column block layout, and textual elements are repositioned.

```css
@media (max-width: 860px) {
  .hero-inner, 
  .day-head, 
  .columns, 
  .landing-links, 
  .trend-panel { 
    grid-template-columns: 1fr; 
  }
  .stamp { 
    text-align: left; 
  }
  .day { 
    padding: 18px; 
  }
  h2 { 
    font-size: 30px; 
  }
}
```