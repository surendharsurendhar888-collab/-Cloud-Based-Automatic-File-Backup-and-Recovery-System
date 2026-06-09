/**
 * CloudProtect AI — Dark / Light Mode Theme Toggle
 * ─────────────────────────────────────────────────
 * - Reads saved preference from localStorage on every page load.
 * - Applies data-theme to <html> BEFORE first paint → no flash.
 * - Wires a single click/touch listener to #dropdownThemeToggle.
 * - Updates icon + label text to always show the *next* action.
 *   • Current theme is dark  → show "Switch to Light Mode" (moon icon)
 *   • Current theme is light → show "Switch to Dark Mode"  (sun icon)
 * - Default theme: "dark" (preserves existing premium dark design).
 */

(function () {
  "use strict";

  var STORAGE_KEY   = "cloudprotect-theme";
  var DEFAULT_THEME = "dark";

  /* ── Helpers ────────────────────────────────────── */

  function getSaved() {
    try {
      return localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME;
    } catch (_) {
      return DEFAULT_THEME;
    }
  }

  function save(theme) {
    try { localStorage.setItem(STORAGE_KEY, theme); } catch (_) {}
  }

  /* ── Core: apply theme to <html> ──────────────────
     Called immediately (FOUC prevention) AND on every toggle.        */
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  /* ── Update dropdown button label + icon ──────────
     Label always describes what WILL happen on click.                */
  function syncDropdown(theme) {
    var btn   = document.getElementById("dropdownThemeToggle");
    var icon  = document.getElementById("dropdownThemeIcon");
    var label = document.getElementById("dropdownThemeLabel");

    if (!btn) return; // user not logged in / element not in DOM

    if (theme === "dark") {
      // currently dark → clicking will switch to light
      if (icon)  { icon.className  = "bi bi-sun-fill me-3"; }
      if (label) { label.textContent = "Switch to Light Mode"; }
      btn.setAttribute("title", "Switch to Light Mode");
    } else {
      // currently light → clicking will switch to dark
      if (icon)  { icon.className  = "bi bi-moon-stars-fill me-3"; }
      if (label) { label.textContent = "Switch to Dark Mode"; }
      btn.setAttribute("title", "Switch to Dark Mode");
    }
  }

  /* ── Toggle ───────────────────────────────────────*/
  function toggleTheme() {
    var next = getSaved() === "dark" ? "light" : "dark";
    save(next);
    applyTheme(next);
    syncDropdown(next);
  }

  /* ── Init: wire listener ONCE after DOM ready ─────*/
  function init() {
    var btn = document.getElementById("dropdownThemeToggle");
    if (!btn) return;

    // Remove any stale listeners by cloning (safety for SPA-style reloads)
    var fresh = btn.cloneNode(true);
    btn.parentNode.replaceChild(fresh, btn);

    // Attach both click (desktop) and touchend (mobile)
    fresh.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggleTheme();
    });

    fresh.addEventListener("touchend", function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggleTheme();
    }, { passive: false });

    // Sync label/icon to saved theme on page load
    syncDropdown(getSaved());
  }

  /* ── Run immediately: apply theme before first paint ── */
  applyTheme(getSaved());

  /* ── Run after DOM is ready ── */
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  /* ── Global API (optional, for console debugging) ── */
  window.CloudTheme = {
    toggle : toggleTheme,
    set    : function (t) { save(t); applyTheme(t); syncDropdown(t); },
    get    : getSaved,
  };

}());
