# Shared Static Assets

This directory contains shared static assets that can be reused across multiple pages.

## Offline Support (断网支持)

### 🔧 Implementation Details (实现详情)

All external CDN resources have been localized to support offline usage:

#### External Resources Localized (本地化的外部资源):
- **Tailwind CSS**: `https://cdn.tailwindcss.com` → `/static/vendor/tailwind/tailwindcss.min.js`
- **HTMX**: `https://unpkg.com/htmx.org@1.9.12` → `/static/vendor/htmx/htmx.min.js`
- **HTMX JSON Extension**: `https://unpkg.com/htmx.org/dist/ext/json-enc.js` → `/static/vendor/htmx/json-enc.js`
- **Cardmeister**: `https://cardmeister.github.io/elements.cardmeister.min.js` → `/static/vendor/cardmeister/elements.cardmeister.min.js`

#### Updated Templates (更新的模板):
- `poker_teaching_replay.html`
- `poker_teaching_replay_preview_1_1_game_layout.html`
- `poker_teaching_game_ui_skeleton_htmx_tailwind.html`
- `poker_teaching_entry_splash_start_the_session.html`
- `marketing.html`

### 📊 File Sizes (文件大小):
- Tailwind CSS: 398KB
- HTMX: 47KB
- HTMX JSON Extension: 51B
- Cardmeister: 26KB

### ✅ Benefits (优势):
- **Offline Support**: 完全离线支持，无需网络即可使用
- **Faster Loading**: 本地资源加载更快
- **Reliability**: 不依赖外部CDN的可用性
- **Version Control**: 所有资源版本可控

## Theme Toggle Component

The theme toggle functionality has been extracted into reusable components:

### Files:
- `css/theme-toggle.css` - Theme toggle styles
- `js/theme-toggle.js` - Theme toggle JavaScript functionality
- `templates/ui/_theme_toggle.html` - Theme toggle button HTML template

### Usage:

1. **Include CSS in your HTML head:**
   ```html
   <link rel="stylesheet" href="/static/css/theme-toggle.css">
   ```

2. **Include the button in your template:**
   ```html
   {% include "ui/_theme_toggle.html" %}
   ```

3. **Include JavaScript before closing body tag:**
   ```html
   <script src="/static/js/theme-toggle.js"></script>
   ```

### Features:
- Automatic theme detection and persistence using localStorage
- Smooth transitions between themes
- Hover effects on the toggle button
- Works across all pages that include these components

### Example Implementation:
See `poker_teaching_replay.html` and `poker_teaching_game_ui_skeleton_htmx_tailwind.html` for complete examples.
