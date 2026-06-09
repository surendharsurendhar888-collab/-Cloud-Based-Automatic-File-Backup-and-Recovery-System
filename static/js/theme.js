/**
 * CloudProtect AI — Dark / Light Mode Theme Toggle
 * Reads saved preference from localStorage on every page load (runs inline,
 * before paint, to prevent flash of wrong theme).
 * Default: "dark"  (matches the existing premium dark design)
 */

(function () {
  "use strict";

  const STORAGE_KEY = "cloudprotect-theme";
  const DEFAULT_THEME = "dark";

  /* ── Apply theme to <html> immediately (no FOUC) ── */
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    // Keep body class in sync for Bootstrap-aware overrides
    document.body.classList.toggle("theme-light", theme === "light");
    document.body.classList.toggle("theme-dark", theme === "dark");
  }

  /* ── Persist and broadcast the chosen theme ── */
  function setTheme(theme) {
    localStorage.setItem(STORAGE_KEY, theme);
    applyTheme(theme);
    updateToggles(theme);
  }

  /* ── Return saved or default theme ── */
  function getSavedTheme() {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME;
  }

  /* ── Update every toggle button/icon on the page ── */
  function updateToggles(theme) {
    const isDark = theme === "dark";

    document.querySelectorAll(".theme-toggle-btn").forEach(function (btn) {
      const iconEl = btn.querySelector(".theme-icon");
      const labelEl = btn.querySelector(".theme-label");

      if (iconEl) {
        iconEl.className = "bi theme-icon " + (isDark ? "bi-sun-fill" : "bi-moon-stars-fill");
      }
      if (labelEl) {
        labelEl.textContent = isDark ? "Light Mode" : "Dark Mode";
      }

      btn.setAttribute("aria-label", isDark ? "Switch to Light Mode" : "Switch to Dark Mode");
      btn.setAttribute("title", isDark ? "Switch to Light Mode" : "Switch to Dark Mode");
    });
  }

  /* ── Toggle between dark and light ── */
  function toggleTheme() {
    const current = getSavedTheme();
    setTheme(current === "dark" ? "light" : "dark");
  }

  /* ── Wire up all toggle buttons once DOM is ready ── */
  function initToggles() {
    document.querySelectorAll(".theme-toggle-btn").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        toggleTheme();
      });
    });

    // Reflect current state on first render
    updateToggles(getSavedTheme());
  }

  /* ── Bootstrap: apply saved theme immediately (FOUC prevention) ── */
  applyTheme(getSavedTheme());

  /* ── Attach toggle listeners after DOM load ── */
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initToggles);
  } else {
    initToggles();
  }

  /* ── Expose globally so inline handlers can also call it ── */
  window.CloudTheme = {
    toggle: toggleTheme,
    set: setTheme,
    get: getSavedTheme,
  };
})();
