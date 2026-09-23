// Вкладка «Лента новостей»: загрузка/фильтрация постов, обновление.

import { $, api, escapeHtml, toast } from "./core.js";
import { state } from "./state.js";
import { buildPostEl } from "./components.js";

export function updateSourceLabel() {
  const label = $("#posts-source-label");
  const clearChip = $("#chip-clear-source");
  if (state.currentSource) {
    label.textContent = `(фильтр: @${state.currentSource})`;
    clearChip.style.display = "";
  } else {
    label.textContent = "";
    clearChip.style.display = "none";
  }
}

export function syncChips() {
  document.querySelectorAll(".chip").forEach((c) =>
    c.classList.toggle("active", (c.dataset.kind || "") === state.currentKind)
  );
}

function _clearTagFilter() {
  state.currentTag = "";
  const tf = document.getElementById("tag-filter");
  if (tf) tf.value = "";
}

export async function loadPosts() {
  updateSourceLabel();
  const box = $("#posts");
  box.innerHTML = "Загрузка…";
  let path;
  if (state.currentTag) {
    path = `/api/posts?tag=${encodeURIComponent(state.currentTag)}`;
  } else if (state.currentSource) {
    path = `/api/posts?source=${encodeURIComponent(state.currentSource)}`;
  } else if (state.currentKind) {
    path = `/api/posts?kind=${encodeURIComponent(state.currentKind)}`;
  } else {
    path = "/api/posts";
  }
  try {
    const data = await api(path);
    if (!data.posts.length) {
      box.innerHTML =
        '<div class="empty">Постов пока нет. Нажмите «Свежие за 24ч», чтобы подтянуть новости.</div>';
      return;
    }
    box.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const p of data.posts) frag.appendChild(buildPostEl(p));
    box.appendChild(frag);
    await decoratePostTags(box, data.posts);
  } catch (e) {
    box.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

// Подтянуть теги пользователя (темы) для постов и подписать карточки.
async function decoratePostTags(box, posts) {
  const ids = posts.filter((p) => p.id != null).map((p) => p.id);
  if (!ids.length) return;
  try {
    const tagsMap = await api("/api/posts/tags?ids=" + ids.join(","));
    for (const p of posts) {
      const tags = tagsMap[String(p.id)];
      if (!tags || !tags.length) continue;
      const el = box.querySelector(`.post[data-id="${p.id}"]`);
      if (!el) continue;
      const tagsHtml = tags
        .map(
          (t) =>
            `<span class="usertag" title="тема: ${escapeHtml(t.name)}">${escapeHtml(t.tag)}</span>`
        )
        .join("");
      const existing = el.querySelector(".post-tags");
      if (existing) {
        existing.outerHTML = `<div class="post-tags">${tagsHtml}</div>`;
      } else {
        el.insertAdjacentHTML("beforeend", `<div class="post-tags">${tagsHtml}</div>`);
      }
    }
  } catch (_e) {
    /* теги некритичны — пропускаем */
  }
}

// Добавить свежие посты (последние сутки) строго сверху, не перерисовывая уже загруженные.
export async function prependFresh() {
  const box = $("#posts");
  let path;
  if (state.currentSource) {
    path = `/api/posts?source=${encodeURIComponent(state.currentSource)}`;
  } else if (state.currentKind) {
    path = `/api/posts?kind=${encodeURIComponent(state.currentKind)}`;
  } else {
    path = "/api/posts";
  }
  const data = await api(path);
  const existing = new Set(
    [...box.querySelectorAll(".post")].map((el) => el.dataset.id)
  );
  const fresh = data.posts.filter((p) => p.id != null && !existing.has(String(p.id)));
  if (!fresh.length) return 0;
  const frag = document.createDocumentFragment();
  for (const p of fresh) frag.appendChild(buildPostEl(p));
  box.insertBefore(frag, box.firstChild);
  const empty = box.querySelector(".empty");
  if (empty) empty.remove();
  await decoratePostTags(box, fresh);
  return fresh.length;
}

export function initPosts() {
  $("#refresh-posts").addEventListener("click", async () => {
    const btn = $("#refresh-posts");
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Обновление…";
    try {
      const r = await api("/api/refresh/posts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days: 1 }),
      });
      const added = await prependFresh();
      const extra = added ? `, добавлено ${added} новых сверху` : "";
      toast(`Подтянуто: ${r.fetched ?? 0} источников (ошибок: ${r.failed ?? 0})${extra}`);
    } catch (e) {
      toast(e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  });

  // Фильтры по типу источника (Все / Telegram / RSS)
  document.querySelectorAll(".chip").forEach((c) =>
    c.addEventListener("click", () => {
      if (c.dataset.kind === "__clear_source") return;
      state.currentKind = c.dataset.kind || "";
      state.currentSource = "";
      _clearTagFilter();
      syncChips();
      loadPosts();
    })
  );

  // Выпадающее меню тегов — фильтр ленты по тегу темы.
  const tagFilterEl = document.getElementById("tag-filter");
  if (tagFilterEl) {
    tagFilterEl.addEventListener("change", () => {
      state.currentTag = tagFilterEl.value;
      state.currentSource = "";
      state.currentKind = "";
      syncChips();
      loadPosts();
    });
  }

  $("#chip-clear-source").addEventListener("click", () => {
    state.currentSource = "";
    state.currentKind = "";
    _clearTagFilter();
    syncChips();
    loadPosts();
  });
}
