// Переиспользуемые компоненты: карточка поста и выпадающее меню «＋».

import { $, api, escapeHtml, renderBody, toast } from "./core.js";
import { state } from "./state.js";

export function buildPostEl(p, topicsForPost = []) {
  const el = document.createElement("div");
  el.className = "post";
  if (p.id != null) el.dataset.id = String(p.id);
  const url = p.url
    ? `<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">открыть</a>`
    : "";
  const srcTag = p.source ? `<span class="srcname">@${escapeHtml(p.source)}</span> · ` : "";
  const kindTag = p.kind
    ? `<span class="badge ${escapeHtml(p.kind)}">${escapeHtml(p.kind)}</span> `
    : "";
  // Теги пользователя (темы), к которым отнесён пост.
  const tagsHtml = topicsForPost.length
    ? `<div class="post-tags">` +
      topicsForPost
        .map(
          (t) =>
            `<span class="usertag" title="тема: ${escapeHtml(t.name)}">${escapeHtml(t.tag)}</span>`
        )
        .join("") +
      `</div>`
    : "";
  el.innerHTML = `<div class="posthead">${kindTag}${srcTag}${escapeHtml(p.date || "—")} · ${url}
        <button class="addbtn" title="Добавить в тему">＋</button></div>
      <div class="text">${renderBody(p.text)}</div>${tagsHtml}`;
  el.querySelector(".addbtn").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleAddMenu(el, p.id);
  });
  return el;
}

let addMenuEl = null;
function closeAddMenu() {
  if (addMenuEl) {
    addMenuEl.remove();
    addMenuEl = null;
  }
  document.removeEventListener("click", _outsideAdd, true);
}
function _outsideAdd(e) {
  if (addMenuEl && !addMenuEl.contains(e.target)) closeAddMenu();
}

// Добавить/убрать usertag-чип темы прямо на карточке поста (без перезагрузки ленты).
function addUsertag(el, t) {
  let box = el.querySelector(".post-tags");
  if (!box) {
    box = document.createElement("div");
    box.className = "post-tags";
    el.appendChild(box);
  }
  const exists = [...box.querySelectorAll(".usertag")].some((s) => s.textContent === t.tag);
  if (!exists) {
    const span = document.createElement("span");
    span.className = "usertag";
    span.title = `тема: ${t.name}`;
    span.textContent = t.tag;
    box.appendChild(span);
  }
}

function removeUsertag(el, tag) {
  el.querySelectorAll(".post-tags .usertag").forEach((s) => {
    if (s.textContent === tag) s.remove();
  });
}

export function toggleAddMenu(el, postId) {
  if (addMenuEl) {
    closeAddMenu();
    return;
  }
  const btn = el.querySelector(".addbtn");
  const rect = btn.getBoundingClientRect();
  const menu = document.createElement("div");
  menu.className = "addmenu-pop addmenu-list";
  const title = document.createElement("div");
  title.className = "addmenu-title";
  title.textContent = "Добавить или убрать пост из темы:";
  menu.appendChild(title);
  if (!state.allTopics.length) {
    const empty = document.createElement("div");
    empty.className = "addmenu-empty";
    empty.textContent = "Сначала создайте тему во вкладке «Мои темы».";
    menu.appendChild(empty);
  } else {
    // Текущие теги поста (из уже отрисованных usertag-чипов) — чтобы
    // показать, в какие темы пост уже добавлен, и сделать меню переключающим.
    const current = new Set(
      [...el.querySelectorAll(".post-tags .usertag")].map((s) => s.textContent)
    );
    const list = document.createElement("div");
    list.className = "addmenu-items";
    for (const t of state.allTopics) {
      const added = current.has(t.tag);
      const item = document.createElement("button");
      item.type = "button";
      item.className = "addmenu-item" + (added ? " added" : "");
      item.innerHTML =
        `<span class="ai-name">${escapeHtml(t.name)}</span>` +
        `<span class="ai-tag">${escapeHtml(t.tag)}</span>` +
        `<span class="ai-state"></span>`;
      item.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const isAdded = item.classList.contains("added");
        try {
          if (!isAdded) {
            await api(`/api/topics/posts?name=${encodeURIComponent(t.name)}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ post_id: postId }),
            });
            addUsertag(el, t);
            item.classList.add("added");
            toast(`Добавлено в «${t.name}»`);
          } else {
            await api(
              `/api/topics/posts?name=${encodeURIComponent(t.name)}&post_id=${encodeURIComponent(postId)}`,
              { method: "DELETE" }
            );
            removeUsertag(el, t.tag);
            item.classList.remove("added");
            toast(`Убрано из «${t.name}»`);
          }
          closeAddMenu();
        } catch (err) {
          toast(err.message, true);
        }
      });
      list.appendChild(item);
    }
    menu.appendChild(list);
  }
  document.body.appendChild(menu);
  addMenuEl = menu;
  const mw = menu.offsetWidth,
    mh = menu.offsetHeight;
  let left = rect.left;
  let top = rect.bottom + 6;
  left = Math.min(left, window.innerWidth - mw - 8);
  left = Math.max(left, 8);
  top = Math.min(top, window.innerHeight - mh - 8);
  menu.style.left = left + "px";
  menu.style.top = top + "px";
  setTimeout(() => document.addEventListener("click", _outsideAdd, true), 0);
}
