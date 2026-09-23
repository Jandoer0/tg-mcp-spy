// Общие утилиты: выборка элементов, API-клиент, тосты, безопасный рендер.

export const $ = (sel) => document.querySelector(sel);

let _toastTimer;
export function toast(msg, isErr = false) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => (el.className = "toast"), 2600);
}

export async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = null;
  try {
    data = await res.json();
  } catch (_e) {
    /* пусто */
  }
  if (!res.ok) throw new Error((data && data.error) || `Ошибка ${res.status}`);
  return data;
}

export function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  }[c]));
}

// Безопасный рендер HTML из лент (убираем script/style, обработчики on* и опасные ссылки)
export function sanitizeHtml(html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = html || "";
  tpl.content
    .querySelectorAll("script,style,iframe,object,embed,link,meta,noscript")
    .forEach((e) => e.remove());
  tpl.content.querySelectorAll("*").forEach((el) => {
    for (const a of Array.from(el.attributes)) {
      const n = a.name.toLowerCase();
      const v = a.value.trim().toLowerCase();
      if (
        n.startsWith("on") ||
        ((n === "href" || n === "src") &&
          (v.startsWith("javascript:") || v.startsWith("data:text/html")))
      ) {
        el.removeAttribute(a.name);
      }
    }
  });
  tpl.content
    .querySelectorAll("a")
    .forEach((a) => {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener");
    });
  return tpl.innerHTML;
}

// Если в тексте есть HTML-разметка — рендерим безопасно, иначе экранируем.
export function renderBody(text) {
  const t = text || "";
  if (/<[a-z][\s\S]*>/i.test(t)) return sanitizeHtml(t);
  return escapeHtml(t).replace(/\n/g, "<br>");
}
