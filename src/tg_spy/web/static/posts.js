// Вкладка «Лента новостей»: загрузка/фильтрация постов, обновление.
// Поддерживает бесконечную прокрутку (первые N, догрузка при скролле)
// и фильтр по нескольким тегам (логическое И — посты со всеми тегами).

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

// Построить строку запроса к /api/posts с учётом текущего фильтра и пагинации.
function postsParams() {
  const params = new URLSearchParams();
  if (state.currentTags.length) {
    params.set("tags", state.currentTags.join(","));
  } else if (state.currentSource) {
    params.set("source", state.currentSource);
  } else if (state.currentKind) {
    params.set("kind", state.currentKind);
  }
  params.set("offset", String(state.postsOffset));
  params.set("limit", String(state.postsLimit));
  return params.toString();
}

export async function loadPosts(reset = true) {
  if (reset) {
    state.postsOffset = 0;
    state.postsHasMore = true;
  }
  updateSourceLabel();
  const box = $("#posts");
  if (reset) box.innerHTML = "Загрузка…";
  try {
    const data = await api("/api/posts?" + postsParams());
    if (reset) {
      if (!data.posts.length) {
        box.innerHTML =
          '<div class="empty">Постов пока нет. Нажмите «Свежие за 24ч», чтобы подтянуть новости.</div>';
        state.postsHasMore = false;
        return;
      }
      box.innerHTML = "";
    }
    const frag = document.createDocumentFragment();
    for (const p of data.posts) frag.appendChild(buildPostEl(p));
    box.appendChild(frag);
    await decoratePostTags(box, data.posts);
    state.postsOffset += data.posts.length;
    state.postsHasMore = data.posts.length === state.postsLimit;
  } catch (e) {
    if (reset) box.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

// Подгрузить следующую страницу и дописать в конец (бесконечная прокрутка).
async function loadMorePosts() {
  if (state.postsLoading || !state.postsHasMore) return;
  state.postsLoading = true;
  const box = $("#posts");
  try {
    const data = await api("/api/posts?" + postsParams());
    if (!data.posts.length) {
      state.postsHasMore = false;
      return;
    }
    const frag = document.createDocumentFragment();
    for (const p of data.posts) frag.appendChild(buildPostEl(p));
    box.appendChild(frag);
    await decoratePostTags(box, data.posts);
    state.postsOffset += data.posts.length;
    state.postsHasMore = data.posts.length === state.postsLimit;
  } catch (e) {
    toast(e.message, true);
  } finally {
    state.postsLoading = false;
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
  if (state.currentTags.length) {
    path = `/api/posts?tags=${encodeURIComponent(state.currentTags.join(","))}`;
  } else if (state.currentSource) {
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

// ----- Фильтр по тегам (выпадающий список с возможностью выбрать несколько) -----
export function populateTagFilter() {
  const list = document.getElementById("tag-filter-list");
  if (!list) return;
  list.innerHTML = state.allTopics
    .map(
      (t) =>
        `<label class="tf-row" title="${escapeHtml(t.name)}"><input type="checkbox" value="${escapeHtml(t.tag)}" ${
          state.currentTags.includes(t.tag) ? "checked" : ""
        }/> ${escapeHtml(t.tag)}</label>`
    )
    .join("");
  const all = document.getElementById("tag-filter-all");
  if (all) all.checked = state.currentTags.length === 0;
  updateTagFilterLabel();
}

function updateTagFilterLabel() {
  const btn = document.getElementById("tag-filter-btn");
  if (!btn) return;
  btn.textContent = state.currentTags.length
    ? "Теги: " + state.currentTags.join(", ")
    : "Теги: все";
}

function syncTagFilterUI() {
  const list = document.getElementById("tag-filter-list");
  if (list) {
    list.querySelectorAll("input[type=checkbox]").forEach((cb) => {
      cb.checked = state.currentTags.includes(cb.value);
    });
  }
  const all = document.getElementById("tag-filter-all");
  if (all) all.checked = state.currentTags.length === 0;
  updateTagFilterLabel();
}

function _clearTagFilter() {
  state.currentTags = [];
  syncTagFilterUI();
}

// Пересчитать выбранные теги после изменения любого чекбокса фильтра.
function onTagFilterChange(e) {
  const all = document.getElementById("tag-filter-all");
  const list = document.getElementById("tag-filter-list");
  if (e && e.target === all) {
    if (all.checked) {
      list.querySelectorAll("input[type=checkbox]").forEach((cb) => (cb.checked = false));
    }
  } else if (all && list) {
    const anyChecked = [...list.querySelectorAll("input[type=checkbox]:checked")].length > 0;
    all.checked = !anyChecked;
  }
  state.currentTags = all && all.checked
    ? []
    : [...list.querySelectorAll("input[type=checkbox]:checked")].map((cb) => cb.value);
  state.currentSource = "";
  state.currentKind = "";
  syncChips();
  updateTagFilterLabel();
  loadPosts();
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

  // Выпадающий список тегов — можно выбрать несколько (фильтр по пересечению тем).
  const tagWrap = document.getElementById("tag-filter");
  const tagBtn = document.getElementById("tag-filter-btn");
  const tagPop = document.getElementById("tag-filter-pop");
  const tagAll = document.getElementById("tag-filter-all");
  const tagList = document.getElementById("tag-filter-list");
  if (tagBtn) {
    tagBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const hidden = tagPop.classList.toggle("hidden");
      tagBtn.setAttribute("aria-expanded", String(!hidden));
    });
  }
  if (tagAll) tagAll.addEventListener("change", onTagFilterChange);
  if (tagList) tagList.addEventListener("change", onTagFilterChange);
  document.addEventListener("click", (e) => {
    if (tagWrap && tagPop && !tagWrap.contains(e.target)) {
      tagPop.classList.add("hidden");
      if (tagBtn) tagBtn.setAttribute("aria-expanded", "false");
    }
  });

  $("#chip-clear-source").addEventListener("click", () => {
    state.currentSource = "";
    state.currentKind = "";
    _clearTagFilter();
    syncChips();
    loadPosts();
  });

  // Бесконечная прокрутка: догружаем следующую страницу у нижнего края.
  window.addEventListener("scroll", () => {
    const tab = document.getElementById("tab-posts");
    if (!tab || tab.classList.contains("hidden")) return;
    if (state.postsLoading || !state.postsHasMore) return;
    const y = window.scrollY || window.pageYOffset || 0;
    const nearBottom =
      y + window.innerHeight >= document.documentElement.scrollHeight - 400;
    if (nearBottom) loadMorePosts();
  });
}
