// Переиспользуемые компоненты: карточка поста и выпадающее меню «＋».

import { $, api, escapeHtml, renderBody, toast } from "./core.js";
import { state } from "./state.js";

export function buildPostEl(p) {
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
  el.innerHTML = `<div class="posthead">${kindTag}${srcTag}${escapeHtml(p.date || "—")} · ${url}
        <button class="addbtn" title="Добавить в тему">＋</button></div><div class="text">${renderBody(p.text)}</div>`;
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
  menu.className = "addmenu-pop";
  const sel = document.createElement("select");
  if (!state.allTopics.length) {
    sel.innerHTML = '<option value="">— сначала создайте тему —</option>';
  } else {
    sel.innerHTML = state.allTopics
      .map(
        (t) =>
          `<option value="${escapeHtml(t.name)}">${escapeHtml(t.name)} — ${escapeHtml(t.tag)}</option>`
      )
      .join("");
  }
  const ok = document.createElement("button");
  ok.textContent = "Добавить";
  ok.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    const name = sel.value;
    if (!name) {
      toast("Сначала создайте тему", true);
      return;
    }
    try {
      await api(`/api/topics/posts?name=${encodeURIComponent(name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ post_id: postId }),
      });
      toast(`Добавлено в «${name}»`);
      closeAddMenu();
    } catch (err) {
      toast(err.message, true);
    }
  });
  const cancel = document.createElement("button");
  cancel.className = "ghost";
  cancel.textContent = "Отмена";
  cancel.addEventListener("click", (ev) => {
    ev.stopPropagation();
    closeAddMenu();
  });
  menu.appendChild(sel);
  menu.appendChild(ok);
  menu.appendChild(cancel);
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
