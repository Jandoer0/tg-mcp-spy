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

  // ИИ-редактор: состояние и версия текста.
  const editorStatus = p.editor_status || "none";
  const editorActive = Number(p.editor_active || 0) === 1;
  const hasEdited = !!(p.text_edited && String(p.text_edited).trim());
  // Какой текст показываем: редакцию (если активна и есть), иначе оригинал.
  const showEdited = editorActive && hasEdited;
  const displayText = showEdited ? p.text_edited : p.text;
  const editorState = editorStatus === "editing"
    ? "editing"
    : hasEdited
    ? "done"
    : "none";
  const editorLabel =
    editorState === "editing" ? "ИИ редактор…"
    : editorState === "done" ? "ИИ редактор"
    : "ИИ редактор";
  const editorTag = `<button class="editortag ${editorState}${showEdited ? " lit" : ""}" title="ИИ-редактор: ${editorState === "editing" ? "обработка…" : editorState === "done" ? "готово" : "не обработано"}">✨ ${escapeHtml(editorLabel)}</button>`;

  // Теги пользователя (темы). Берём из кэша postTags (его наполняет
  // decoratePostTags), иначе из topicsForPost — чтобы чипы отрисовывались
  // сразу при любом фильтре, без ожидания второго запроса к API.
  const _pid = String(p.id);
  const _tags = topicsForPost.length
    ? topicsForPost
    : state.postTags[_pid] && state.postTags[_pid].length
    ? state.postTags[_pid]
    : [];
  const tagsHtml = _tags.length
    ? `<div class="post-tags">` +
      _tags
        .map(
          (t) =>
            `<span class="usertag" title="тема: ${escapeHtml(t.name)}">${escapeHtml(t.tag)}</span>`
        )
        .join("") +
      `</div>`
    : "";
  el.innerHTML = `<div class="posthead">${kindTag}${srcTag}${escapeHtml(p.date || "—")} · ${url}
        ${editorTag}
        <button class="addbtn" title="Добавить в тему">＋</button></div>
      <div class="text">${renderBody(displayText)}</div>${tagsHtml}`;
  el.querySelector(".addbtn").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleAddMenu(el, p.id);
  });
  el.querySelector(".editortag").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleEditorMenu(el, p);
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

// --------------------------------------------------------------------------- #
// Меню ИИ-редактора поста: персональная обработка на лету.
// --------------------------------------------------------------------------- #
let editorMenuEl = null;
function closeEditorMenu() {
  if (editorMenuEl) {
    editorMenuEl.remove();
    editorMenuEl = null;
  }
  document.removeEventListener("click", _outsideEditor, true);
}
function _outsideEditor(e) {
  if (editorMenuEl && !editorMenuEl.contains(e.target)) closeEditorMenu();
}

async function refreshPostEditor(el, postId) {
  // Перечитать состояние редактора поста и обновить индикатор в DOM.
  try {
    const data = await api(`/api/posts/editor?ids=${encodeURIComponent(postId)}`);
    const st = data[String(postId)] || { status: "none", active: 0, has_edited: false };
    state.postEditor[String(postId)] = st;
    const tag = el.querySelector(".editortag");
    const editing = st.status === "editing";
    const lit = st.has_edited && st.active;
    if (tag) {
      tag.className = `editortag ${editing ? "editing" : st.has_edited ? "done" : "none"}${lit ? " lit" : ""}`;
    }
  } catch (_e) {
    /* тихо */
  }
}

export function toggleEditorMenu(el, p) {
  if (editorMenuEl) {
    closeEditorMenu();
    return;
  }
  const postId = p.id;
  const btn = el.querySelector(".editortag");
  const rect = btn.getBoundingClientRect();
  const menu = document.createElement("div");
  menu.className = "addmenu-pop addmenu-list";
  const title = document.createElement("div");
  title.className = "addmenu-title";
  title.textContent = "ИИ-редактор поста:";
  menu.appendChild(title);

  const hasEdited = !!(p.text_edited && String(p.text_edited).trim());
  const editorActive = Number(p.editor_active || 0) === 1;

  const actions = [];
  // 1) Запустить/перезапустить редактуру (если ещё не в процессе).
  actions.push({
    label: p.editor_status === "editing" ? "Редактура выполняется…" : "Отредактировать пост",
    cls: p.editor_status === "editing" ? "disabled" : "",
    run: async () => {
      if (p.editor_status === "editing") return;
      try {
        await api(`/api/editor/post?post_id=${encodeURIComponent(postId)}`, { method: "POST" });
        p.editor_status = "editing";
        const tag = el.querySelector(".editortag");
        if (tag) tag.className = "editortag editing";
        toast("ИИ-редактор обрабатывает пост…");
      } catch (e) { toast(e.message, true); }
    },
  });
  // 2) Показать оригинал / редакцию.
  if (hasEdited) {
    actions.push({
      label: editorActive ? "Показать оригинал" : "Показать отредактированное",
      cls: "",
      run: async () => {
        try {
          const active = !editorActive;
          await api(`/api/editor/post/active?post_id=${encodeURIComponent(postId)}&active=${active ? 1 : 0}`, { method: "POST" });
          p.editor_active = active ? 1 : 0;
          const textEl = el.querySelector(".text");
          if (textEl) textEl.innerHTML = renderBody(active ? p.text_edited : p.text);
          const tag = el.querySelector(".editortag");
          if (tag) tag.classList.toggle("lit", active);
          toast(active ? "Показана редакция ИИ" : "Показан оригинал");
        } catch (e) { toast(e.message, true); }
      },
    });
  }
  // 3) Удалить ИИ-редакцию.
  if (hasEdited) {
    actions.push({
      label: "Удалить ИИ-редакцию",
      cls: "danger",
      run: async () => {
        if (!confirm("Удалить сохранённую ИИ-редакцию этого поста?")) return;
        try {
          await api(`/api/editor/post?post_id=${encodeURIComponent(postId)}`, { method: "DELETE" });
          p.text_edited = null;
          p.editor_status = "none";
          p.editor_active = 0;
          const textEl = el.querySelector(".text");
          if (textEl) textEl.innerHTML = renderBody(p.text);
          const tag = el.querySelector(".editortag");
          if (tag) tag.className = "editortag none";
          toast("ИИ-редакция удалена");
        } catch (e) { toast(e.message, true); }
      },
    });
  }

  const list = document.createElement("div");
  list.className = "addmenu-items";
  for (const a of actions) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "addmenu-item" + (a.cls ? " " + a.cls : "");
    item.textContent = a.label;
    if (!a.cls.includes("disabled")) {
      item.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        await a.run();
        closeEditorMenu();
      });
    } else {
      item.disabled = true;
    }
    list.appendChild(item);
  }
  menu.appendChild(list);
  document.body.appendChild(menu);
  editorMenuEl = menu;
  const mw = menu.offsetWidth,
    mh = menu.offsetHeight;
  let left = rect.left;
  let top = rect.bottom + 6;
  left = Math.min(left, window.innerWidth - mw - 8);
  left = Math.max(left, 8);
  top = Math.min(top, window.innerHeight - mh - 8);
  menu.style.left = left + "px";
  menu.style.top = top + "px";
  setTimeout(() => document.addEventListener("click", _outsideEditor, true), 0);
}
