// Вкладка «Подписки»: список, удаление, формы добавления.

import { $, api, escapeHtml, toast } from "./core.js";
import { state } from "./state.js";
import { switchTab } from "./nav.js";
import { syncChips } from "./posts.js";

export async function loadSources() {
  const box = $("#sources");
  try {
    const sources = await api("/api/sources");
    if (!sources.length) {
      box.innerHTML =
        '<div class="empty">Пока нет подписок. Добавьте канал или ленту ниже.</div>';
      return;
    }
    box.innerHTML = "";
    for (const s of sources) {
      const el = document.createElement("div");
      el.className = "src";
      const href =
        s.kind === "rss" && s.url ? s.url : `https://t.me/${s.name}`;
      el.innerHTML = `
        <div class="top">
          <span class="badge ${s.kind}">${s.kind}</span>
          <span class="name">@${escapeHtml(s.name)}</span>
          <span class="meta"></span>
          <button class="link" data-posts="${escapeHtml(s.name)}">посты</button>
          <button class="danger" data-del="${escapeHtml(s.name)}">удалить</button>
        </div>
        <a class="url" href="${escapeHtml(href)}" target="_blank" rel="noopener" title="${escapeHtml(href)}">${escapeHtml(href)}</a>`;
      box.appendChild(el);
    }
    box
      .querySelectorAll("[data-del]")
      .forEach((b) => b.addEventListener("click", () => delSource(b.dataset.del)));
    box
      .querySelectorAll("[data-posts]")
      .forEach((b) =>
        b.addEventListener("click", () => {
          state.currentSource = b.dataset.posts;
          state.currentKind = "";
          syncChips();
          switchTab("posts");
        })
      );
  } catch (e) {
    box.innerHTML = `<div class="empty">Не удалось загрузить: ${e.message}</div>`;
  }
}

async function delSource(name) {
  if (!confirm(`Удалить подписку @${name}?`)) return;
  try {
    await api(`/api/sources/${encodeURIComponent(name)}`, { method: "DELETE" });
    toast("Удалено");
    loadSources();
  } catch (e) {
    toast(e.message, true);
  }
}

export function initSubs() {
  $("#form-tg").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = e.target.name.value.trim();
    try {
      await api("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "telegram", name }),
      });
      toast("Канал добавлен");
      e.target.reset();
      loadSources();
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("#form-rss").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = e.target.name.value.trim();
    const url = e.target.url.value.trim();
    try {
      await api("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "rss", name, url }),
      });
      toast("Лента добавлена");
      e.target.reset();
      loadSources();
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("#form-rsshub").addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = e.target.username.value.trim();
    const base = e.target.base.value.trim();
    try {
      const { url } = await api(
        `/api/rsshub?username=${encodeURIComponent(username)}` +
          (base ? `&base=${encodeURIComponent(base)}` : "")
      );
      await api("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "rss", name: username, url }),
      });
      toast("Добавлено через RSSHub");
      e.target.reset();
      loadSources();
    } catch (err) {
      toast(err.message, true);
    }
  });
}
