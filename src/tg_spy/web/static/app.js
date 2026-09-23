// Точка входа фронтенда: проводка модулей и стартовая загрузка.

import { initTheme } from "./theme.js";
import { initNav } from "./nav.js";
import { initPosts, loadPosts } from "./posts.js";
import { initSubs, loadSources } from "./subs.js";
import { initTopics, loadAllTopics } from "./topics.js";

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
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
