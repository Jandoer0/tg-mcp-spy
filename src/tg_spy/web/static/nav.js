// Переключение вкладок и проводка кнопок навигации.

import { $ } from "./core.js";
import { loadPosts, populateTagFilter } from "./posts.js";
import { loadConfig, loadTopics, loadAllTopics, startTopicsPolling, stopTopicsPolling, initEditorCard } from "./topics.js";

export function switchTab(tab) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === tab)
  );
  $("#tab-posts").classList.toggle("hidden", tab !== "posts");
  $("#tab-subs").classList.toggle("hidden", tab !== "subs");
  $("#tab-mytopics").classList.toggle("hidden", tab !== "mytopics");
  $("#tab-settings").classList.toggle("hidden", tab !== "settings");
  stopTopicsPolling();
  if (tab === "posts") {
    populateTagFilter();
    loadPosts();
  }
  if (tab === "mytopics") {
    loadConfig();
    loadTopics();
    startTopicsPolling();
  }
  if (tab === "settings") {
    loadConfig();
    initEditorCard();
  }
}

export function initNav() {
  document
    .querySelectorAll(".tab")
    .forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
}
