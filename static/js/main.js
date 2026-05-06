/* ============================================================
   CloudVault — main.js
   Global JavaScript utilities loaded on every page.
   Page-specific scripts are in the {% block scripts %} blocks.
   ============================================================ */

"use strict";

// ── Auto-dismiss flash alerts after 4 seconds ────────────────
document.addEventListener("DOMContentLoaded", function () {
  const alerts = document.querySelectorAll("#flashContainer .alert");
  alerts.forEach(function (alert) {
    setTimeout(function () {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      bsAlert.close();
    }, 4000);
  });
});

// ── Navbar active highlight (handles hash/query params) ──────
document.addEventListener("DOMContentLoaded", function () {
  const path  = window.location.pathname;
  const links = document.querySelectorAll(".cv-navbar .nav-link");
  links.forEach(function (link) {
    const href = link.getAttribute("href");
    if (href && path.startsWith(href) && href !== "/") {
      link.classList.add("active");
    }
  });
});

// ── Tooltip initialisation (Bootstrap 5) ────────────────────
document.addEventListener("DOMContentLoaded", function () {
  const tooltipEls = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  tooltipEls.forEach(function (el) {
    new bootstrap.Tooltip(el, { trigger: "hover" });
  });
});

// ── Confirm before navigating to restore / delete links ──────
document.addEventListener("DOMContentLoaded", function () {
  // Any <a> or <button> with data-confirm attribute
  document.querySelectorAll("[data-confirm]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      const msg = this.dataset.confirm || "Are you sure?";
      if (!confirm(msg)) e.preventDefault();
    });
  });
});

// ── Format file size helper (used via inline scripts too) ────
window.formatBytes = function (bytes, decimals = 1) {
  if (!+bytes) return "0 B";
  const k     = 1024;
  const dm    = decimals < 0 ? 0 : decimals;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i     = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
};
