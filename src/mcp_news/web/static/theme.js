// Переключатель темы (светлая / тёмная). Классы проставляются до отрисовки
// отдельным inline-скриптом в <head>; здесь — только логика переключателя.

import { $ } from "./core.js";

export function initTheme() {
  const toggle = document.getElementById("themeToggle");
  const thumb = document.getElementById("themeThumb");
  if (!toggle || !thumb) return;
  let isDark = document.documentElement.classList.contains("dark");
  function apply() {
    document.documentElement.classList.toggle("dark", isDark);
    document.documentElement.classList.toggle("light", !isDark);
    toggle.checked = isDark;
    thumb.textContent = isDark ? "🌙" : "☀️";
  }
  apply();
  toggle.addEventListener("change", function () {
    isDark = toggle.checked;
    try {
      localStorage.setItem("theme", isDark ? "dark" : "light");
    } catch (_e) {
      /* нет доступа к localStorage */
    }
    apply();
  });
}
