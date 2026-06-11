/**
 * CloudProtect AI — Dark / Light Mode Theme Toggle
 * ─────────────────────────────────────────────────
 * - Reads theme preference ("dark" or "light") from localStorage.
 * - Default theme is "light".
 * - Adds "dark-mode" class to <html> early to prevent FOUC (flash of wrong theme).
 * - Toggles "dark-mode" class on <body>, and saves to localStorage.
 * - Supports and synchronizes three toggle elements:
 *   1) Desktop navbar toggle (#themeToggle)
 *   2) Mobile navbar toggle (#mobileThemeToggle)
 *   3) Profile dropdown toggle (#dropdownThemeToggle)
 */

(function () {
  "use strict";

  var STORAGE_KEY = "theme";
  var DEFAULT_THEME = "light";

  // 1. Get saved theme or default
  function getTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME;
    } catch (_) {
      return DEFAULT_THEME;
    }
  }

  // 2. Save theme to localStorage
  function saveTheme(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (_) {}
  }

  // 3. Early apply to <html> to prevent flash before body/DOM exists
  var initialTheme = getTheme();
  if (initialTheme === "dark") {
    document.documentElement.classList.add("dark-mode");
  } else {
    document.documentElement.classList.remove("dark-mode");
  }

  // 4. Synchronize theme toggles UI (icons / labels)
  function syncUI(theme) {
    var isDark = theme === "dark";

    // Desktop navbar icon toggle
    var desktopIcon = document.getElementById("themeToggleIcon");
    if (desktopIcon) {
      desktopIcon.textContent = isDark ? "☀️" : "🌙";
    }

    // Mobile navbar icon toggle
    var mobileIcon = document.getElementById("mobileThemeToggleIcon");
    if (mobileIcon) {
      mobileIcon.textContent = isDark ? "☀️" : "🌙";
    }

    // Profile dropdown toggle
    var dropdownIcon = document.getElementById("dropdownThemeIcon");
    var dropdownLabel = document.getElementById("dropdownThemeLabel");
    var dropdownBtn = document.getElementById("dropdownThemeToggle");

    if (dropdownIcon) {
      dropdownIcon.className = isDark ? "bi bi-sun-fill me-3" : "bi bi-moon-stars-fill me-3";
    }
    if (dropdownLabel) {
      dropdownLabel.textContent = isDark ? "Switch to Light Mode" : "Switch to Dark Mode";
    }
    if (dropdownBtn) {
      dropdownBtn.setAttribute("title", isDark ? "Switch to Light Mode" : "Switch to Dark Mode");
    }
  }

  // 5. Perform theme change
  function toggleTheme() {
    var current = getTheme();
    var next = current === "dark" ? "light" : "dark";

    saveTheme(next);

    // Apply to html and body elements
    if (next === "dark") {
      document.documentElement.classList.add("dark-mode");
      document.body.classList.add("dark-mode");
    } else {
      document.documentElement.classList.remove("dark-mode");
      document.body.classList.remove("dark-mode");
    }

    syncUI(next);
  }

  // 6. Initialize theme class on <body> and setup listeners after DOM loads
  function init() {
    var theme = getTheme();
    
    // Apply class to body
    if (theme === "dark") {
      document.body.classList.add("dark-mode");
    } else {
      document.body.classList.remove("dark-mode");
    }

    // Sync button icons
    syncUI(theme);

    // Wire up events for all toggle button IDs
    var toggleButtons = ["themeToggle", "mobileThemeToggle", "dropdownThemeToggle"];
    toggleButtons.forEach(function (id) {
      var btn = document.getElementById(id);
      if (btn) {
        // Remove old event listeners by cloning
        var freshBtn = btn.cloneNode(true);
        btn.parentNode.replaceChild(freshBtn, btn);

        freshBtn.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          toggleTheme();
        });

        freshBtn.addEventListener("touchend", function (e) {
          e.preventDefault();
          e.stopPropagation();
          toggleTheme();
        }, { passive: false });
      }
    });
  }

  // Bind init to DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Expose toggle Theme API for custom links / debug
  window.CloudTheme = {
    toggle: toggleTheme,
    get: getTheme,
    set: function (theme) {
      saveTheme(theme);
      if (theme === "dark") {
        document.documentElement.classList.add("dark-mode");
        document.body.classList.add("dark-mode");
      } else {
        document.documentElement.classList.remove("dark-mode");
        document.body.classList.remove("dark-mode");
      }
      syncUI(theme);
    }
  };

})();
