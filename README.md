# PDF Viewer Help

A fast, multi-threaded PDF viewer built with PySide6 and PyMuPDF (`fitz`).
It supports single-page and two-page spreads, continuous scrolling, search, drag panning, and fit-to-window zoom.

## Starting the Program

- Run `pdfpro.pyw` directly from Python.
- To open a document immediately, pass the PDF path as a command-line argument:  
  `python pdfpro.pyw "document.pdf"`
- Click **Open PDF** in the sidebar to browse for a file.

## Sidebar Controls

| Button | Action |
|---|---|
| **Open PDF** | Choose a PDF file to view. |
| **Zoom +** | Zoom in by 10% (disables fit-to-window). |
| **Zoom –** | Zoom out by 10% (disables fit-to-window). |
| **Fit page** | Fit the current page/spread to the window. |
| **Continuous / Single-scroll** | Toggle between continuous scroll and single-page view. |
| **Two pages / Single page** | Toggle two-page spreads on or off. |
| **Cover mode / No cover** | When two-page mode is on, show page 1 alone on the first spread (like a book cover). |

## Page Navigation

| Control | Action |
|---|---|
| **Vertical slider** | Jump quickly through pages or scroll position. |
| **Mouse wheel** | In single-page mode, wheel down/up turns to the next/previous page. In continuous mode, the page scrolls normally. |
| **Drag with left mouse** | Pan the page horizontally and vertically when it is larger than the viewport. |

## Search

- Type a term into the **Search text** box in the sidebar.
- Click the **>** arrow button or press <kbd>F3</kbd> to jump to the next match.
- Press <kbd>Shift</kbd>+<kbd>F3</kbd> to jump to the previous match.
- Matching pages are listed in the status area. Matches are highlighted in yellow on the pages.

## Fullscreen

- Double-click anywhere on the page, or on the continuous view, to enter/exit fullscreen.
- When leaving fullscreen, the window returns to its previous size.

## Status Label

The bottom of the sidebar shows:

- Current page number and total pages.
- Current zoom level (e.g., `1.00x`).
- Current view mode (**Continuous** or **Single**).
- Number of pages containing search matches, when searching.

## View Modes Explained

### Single page

Displays one logical page at a time. Use the wheel, slider, or keyboard to move to the next or previous page. Scroll positions are remembered while browsing.

### Continuous

Displays all pages in one long scrollable column. The sidebar slider controls the scroll position. The current page is updated automatically to whichever page is most visible in the viewport.

### Two-page mode

Pairs pages side by side. Use with or without **Cover mode**:

- **Cover mode ON:** page 1 is shown alone, then pages 2–3, 4–5, etc.
- **Cover mode OFF:** pages are paired 1–2, 3–4, 5–6, etc.

> **Tip:** In fit mode, zoom is recalculated automatically when you resize the window, switch pages, or change the view layout.

## Rendering

Pages render in parallel on background threads for smooth navigation. If a page is not yet rendered, a placeholder is shown first, and the final image appears as soon as it is ready.

## Keyboard Shortcuts

| Key | Action |
|---|---|
| <kbd>F3</kbd> | Jump to next search result. |
| <kbd>Shift</kbd> + <kbd>F3</kbd> | Jump to previous search result. |

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). See the `LICENSE` file for details.

### Third-party dependencies

This project uses third-party libraries, including:

- **PySide6 / Qt for Python** — available under LGPLv3/GPLv3/commercial Qt licensing
- **PyMuPDF (fitz)** — available under the GNU AGPL or a commercial license from Artifex

Your use, distribution, and deployment of this software must also comply with the licenses of these dependencies.

### Important note for commercial users

If you distribute this application or modified versions of it, you are responsible for complying with the license obligations of all bundled dependencies.

In particular, PyMuPDF is provided under AGPL or a separate commercial license. If AGPL obligations are not acceptable for your use case, you may need to obtain a commercial license for PyMuPDF or replace that dependency.

> **Warning:** This repository is intended to remain open source. If you redistribute modified versions, you must preserve the applicable open-source license terms.

---

PDF Viewer — PySide6 / PyMuPDF based viewer. Help generated for `pdfpro.pyw`.
