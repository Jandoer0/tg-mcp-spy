const $ = (sel) => document.querySelector(sel);
const toastEl = $("#toast");
let toastTimer;

function toast(msg, isErr = false) {
  toastEl.textContent = msg;
  toastEl.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toastEl.className = "toast"), 2600);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch {}
  if (!res.ok) {
    throw new Error((data && data.error) || `Ошибка ${res.status}`);
  }
  return data;
}

async function loadSources() {
  const box = $("#sources");
  try {
    const sources = await api("/api/sources");
    if (!sources.length) {
      box.innerHTML = '<div class="empty">Пока нет подписок. Добавьте канал или ленту ниже.</div>';
      return;
    }
    box.innerHTML = "";
    for (const s of sources) {
      const el = document.createElement("div");
      el.className = "src";
      const meta = s.kind === "rss" && s.url ? s.url : `добавлен ${s.added_at}`;
      el.innerHTML = `
        <span class="badge ${s.kind}">${s.kind}</span>
        <span class="name">@${s.name}</span>
        <span class="meta">${meta}</span>
        <button class="link" data-posts="${s.name}">посты</button>
        <button class="danger" data-del="${s.name}">удалить</button>`;
      box.appendChild(el);
    }
    box.querySelectorAll("[data-del]").forEach((b) =>
      b.addEventListener("click", () => delSource(b.dataset.del))
    );
    box.querySelectorAll("[data-posts]").forEach((b) =>
      b.addEventListener("click", () => loadPosts(b.dataset.posts))
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

async function loadPosts(name) {
  const box = $("#posts");
  box.innerHTML = "Загрузка…";
  try {
    const data = await api(`/api/posts?source=${encodeURIComponent(name)}`);
    if (!data.posts.length) {
      box.innerHTML = '<div class="empty">Постов пока нет. Запросите их через MCP-инструмент query_posts.</div>';
      return;
    }
    box.innerHTML = "";
    for (const p of data.posts) {
      const el = document.createElement("div");
      el.className = "post";
      const url = p.url ? `<a href="${p.url}" target="_blank" rel="noopener">открыть</a>` : "";
      el.innerHTML = `<div class="date">${p.date || "—"} · ${url}</div><div class="text">${escapeHtml(p.text)}</div>`;
      box.appendChild(el);
    }
  } catch (e) {
    box.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

$("#refresh").addEventListener("click", loadSources);

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
    const { url } = await api(`/api/rsshub?username=${encodeURIComponent(username)}` +
      (base ? `&base=${encodeURIComponent(base)}` : ""));
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

loadSources();
