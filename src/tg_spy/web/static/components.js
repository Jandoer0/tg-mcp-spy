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
  title.textContent = "Добавить пост в тему:";
  menu.appendChild(title);
  if (!state.allTopics.length) {
    const empty = document.createElement("div");
    empty.className = "addmenu-empty";
    empty.textContent = "Сначала создайте тему во вкладке «Мои темы».";
    menu.appendChild(empty);
  } else {
    const list = document.createElement("div");
    list.className = "addmenu-items";
    for (const t of state.allTopics) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "addmenu-item";
      item.innerHTML = `<span class="ai-name">${escapeHtml(t.name)}</span><span class="ai-tag">${escapeHtml(t.tag)}</span>`;
      item.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        try {
          await api(`/api/topics/posts?name=${encodeURIComponent(t.name)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ post_id: postId }),
          });
          toast(`Добавлено в «${t.name}»`);
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
