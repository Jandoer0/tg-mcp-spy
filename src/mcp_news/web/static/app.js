// Точка входа фронтенда: проводка модулей и стартовая загрузка.

import { initTheme } from "./theme.js";
import { initNav } from "./nav.js";
import { initPosts, loadPosts } from "./posts.js";
import { initSubs, loadSources } from "./subs.js";
import { initTopics, loadAllTopics, loadConfig } from "./topics.js";

function boot() {
  initTheme();
  initNav();
  initPosts();
  initSubs();
  initTopics();

  // Стартовая загрузка: список подписок + последние посты (главная вкладка).
  loadSources();
  loadPosts();
  loadAllTopics();

  // Подтянуть настройки ИИ/часового пояса из конфига сразу, независимо от
  // того, когда пользователь откроет вкладку «Настройки»/«Мои темы».
  loadConfig();

  // Подстроить высоту липкой шапки ленты под фактическую высоту верхнего
  // header-bar (зависит от темы/ширины), чтобы шапка ленты не перекрывалась.
  const headerBar = document.querySelector(".header-bar");
  const setHeaderH = () => {
    if (headerBar) {
      document.documentElement.style.setProperty("--header-h", headerBar.offsetHeight + "px");
    }
  };
  setHeaderH();
  window.addEventListener("resize", setHeaderH);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
