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
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
