// Вкладка «Мои темы»: список тем, детали, запуск агента, настройки провайдера.

import { $, api, escapeHtml, renderBody, toast } from "./core.js";
import { state } from "./state.js";
import { buildPostEl } from "./components.js";

export async function loadAllTopics() {
  try {
    state.allTopics = await api("/api/topics");
  } catch (_e) {
    state.allTopics = [];
  }
  populateTagFilter();
}

// Заполнить выпадающее меню тегов (фильтр в «Ленте новостей»).
export function populateTagFilter() {
  const sel = document.getElementById("tag-filter");
  if (!sel) return;
  const cur = state.currentTag;
  sel.innerHTML =
    '<option value="">— все теги —</option>' +
    state.allTopics
      .map(
        (t) =>
          `<option value="${escapeHtml(t.tag)}">${escapeHtml(t.tag)} (${escapeHtml(t.name)})</option>`
      )
      .join("");
  sel.value = cur;
}

export async function loadTopics() {
  const box = $("#topics");
  try {
    await loadAllTopics();
    if (!state.allTopics.length) {
      box.innerHTML =
        '<div class="empty">Тем пока нет. Создайте тему ниже — агент сам соберёт по ней посты из ленты.</div>';
      return;
    }
    box.innerHTML = "";
    for (const t of state.allTopics) {
      const el = document.createElement("div");
      el.className = "topic";
      const active = t.active ? "активна" : "выкл.";
      el.innerHTML = `
        <div class="t-top">
          <span class="t-name">${escapeHtml(t.name)}</span>
          <span class="t-tag">тег: ${escapeHtml(t.tag)}</span>
          <span class="t-meta">${active} · постов: ${t.posts_count || 0}<br>${
        t.last_run_at ? "запуск: " + escapeHtml(t.last_run_at) : "ещё не запускался"
      }</span>
        </div>
        ${t.description ? `<div class="t-desc">${escapeHtml(t.description)}</div>` : ""}
        <div class="t-actions">
          <button class="link" data-open="${escapeHtml(t.name)}">открыть</button>
          <button class="link" data-run="${escapeHtml(t.name)}">запустить агента</button>
          <button class="link" data-toggle="${escapeHtml(t.name)}" data-active="${
        t.active ? 1 : 0
      }">${t.active ? "выключить" : "включить"}</button>
          <button class="danger" data-del-topic="${escapeHtml(t.name)}">удалить</button>
        </div>`;
      box.appendChild(el);
    }
    box
      .querySelectorAll("[data-open]")
      .forEach((b) => b.addEventListener("click", () => openTopic(b.dataset.open)));
    box
      .querySelectorAll("[data-run]")
      .forEach((b) => b.addEventListener("click", () => runTopicAgent(b.dataset.run)));
    box
      .querySelectorAll("[data-toggle]")
      .forEach((b) =>
        b.addEventListener("click", () => toggleTopic(b.dataset.toggle, b.dataset.active))
      );
    box
      .querySelectorAll("[data-del-topic]")
      .forEach((b) => b.addEventListener("click", () => delTopic(b.dataset.delTopic)));
  } catch (e) {
    box.innerHTML = `<div class="empty">Не удалось загрузить: ${e.message}</div>`;
  }
}

export async function toggleTopic(name, active) {
  const newActive = active === "1" ? 0 : 1;
  try {
    await api(
      `/api/topics/toggle?name=${encodeURIComponent(name)}&active=${newActive}`,
      { method: "POST" }
    );
    loadTopics();
  } catch (e) {
    toast(e.message, true);
  }
}

export async function delTopic(name) {
  if (!confirm(`Удалить тему «${name}» и её хронологию?`)) return;
  try {
    await api(`/api/topics?name=${encodeURIComponent(name)}`, { method: "DELETE" });
    toast("Тема удалена");
    loadTopics();
  } catch (e) {
    toast(e.message, true);
  }
}

export async function runTopicAgent(name) {
  try {
    const r = await api(`/api/topics/run?name=${encodeURIComponent(name)}`, {
      method: "POST",
    });
    toast(r.message || "Агент запущен");
  } catch (e) {
    toast(e.message, true);
  }
}

export async function openTopic(name) {
  state.currentTopic = name;
  $("#topics-card").classList.add("hidden");
  $("#topic-create-card").classList.add("hidden");
  $("#topic-detail").classList.remove("hidden");
  try {
    const data = await api(`/api/topics/posts?name=${encodeURIComponent(name)}`);
    const t = data.topic || {};
    $("#topic-title").textContent = t.name || name;
    $("#topic-sub").textContent =
      `тег: ${t.tag || ""} · постов: ${data.total || 0}` +
      (t.description ? ` · «${t.description}»` : "");
    const box = $("#topic-posts");
    if (!data.posts.length) {
      box.innerHTML =
        '<div class="empty">Постов в теме пока нет. Нажмите «Запустить агента» или добавьте пост из ленты (кнопка ＋ на посте).</div>';
      return;
    }
    box.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const p of data.posts) {
      const el = document.createElement("div");
      el.className = "post";
      const modeCls = p.mode === "manual" ? "manual" : "tag";
      const modeTxt = p.mode === "manual" ? "вручную" : "по тегу";
      const url = p.url
        ? `<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">источник</a>`
        : "";
      const srcTag = p.source ? `<span class="srcname">@${escapeHtml(p.source)}</span> · ` : "";
      el.innerHTML = `<div class="posthead">${srcTag}${escapeHtml(p.date || "—")} ·
        <span class="mode-badge ${modeCls}">${modeTxt}</span> ${url}
        <button class="danger" data-entry="${p.id}">удалить</button></div><div class="text">${renderBody(p.text)}</div>`;
      frag.appendChild(el);
    }
    box.appendChild(frag);
    box
      .querySelectorAll("[data-entry]")
      .forEach((b) => b.addEventListener("click", () => removeTopicPost(b.dataset.entry)));
  } catch (e) {
    $("#topic-posts").innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

async function removeTopicPost(postId) {
  try {
    await api(
      `/api/topics/posts?name=${encodeURIComponent(state.currentTopic)}&post_id=${encodeURIComponent(postId)}`,
      { method: "DELETE" }
    );
    toast("Удалено из темы");
    openTopic(state.currentTopic);
  } catch (e) {
    toast(e.message, true);
  }
}

// ----- Настройки провайдера / модели ИИ -----
export async function loadConfig() {
  const card = document.getElementById("provider-card");
  if (!card) return;
  try {
    const cfg = await api("/api/config");
    const prov = (cfg.providers && cfg.providers[cfg.provider || "ollama"]) || {};
    card.querySelector("[name=baseUrl]").value = prov.baseUrl || "";
    card.querySelector("[name=model]").value = cfg.model || "";
    card.querySelector("[name=apiKey]").value = prov.apiKey || "";
    card.querySelector("[name=feedRefreshMinutes]").value =
      (cfg.schedule && cfg.schedule.feedRefreshMinutes) || "";
    card.querySelector("[name=topicMinutes]").value =
      (cfg.schedule && cfg.schedule.topicMinutes) || "";
    const compat = prov.compat || {};
    document.getElementById("cfg-dev").checked = !!compat.supportsDeveloperRole;
    document.getElementById("cfg-reason").checked = !!compat.supportsReasoningEffort;
    document.getElementById("cfg-json").checked = !!compat.jsonObjectFormat;
    document.getElementById("cfg-think").checked = !!compat.disableThinking;
  } catch (_e) {
    /* конфиг недоступен — поля останутся пустыми */
  }
}

async function saveConfig() {
  const card = document.getElementById("provider-card");
  const payload = {
    provider: "ollama",
    model: card.querySelector("[name=model]").value.trim(),
    providers: {
      ollama: {
        baseUrl: card.querySelector("[name=baseUrl]").value.trim(),
        apiKey: card.querySelector("[name=apiKey]").value.trim() || "ollama",
        compat: {
          supportsDeveloperRole: document.getElementById("cfg-dev").checked,
          supportsReasoningEffort: document.getElementById("cfg-reason").checked,
          jsonObjectFormat: document.getElementById("cfg-json").checked,
          disableThinking: document.getElementById("cfg-think").checked,
        },
      },
    },
    schedule: {
      feedRefreshMinutes: card.querySelector("[name=feedRefreshMinutes]").value.trim(),
      topicMinutes: card.querySelector("[name=topicMinutes]").value.trim(),
    },
  };
  try {
    await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    document.getElementById("config-status").textContent =
      "Сохранено. Применяется сразу (перезапуск не нужен).";
    toast("Настройки провайдера сохранены");
  } catch (e) {
    document.getElementById("config-status").textContent = "Ошибка: " + e.message;
    toast(e.message, true);
  }
}

async function testConfig() {
  const st = document.getElementById("config-status");
  st.textContent = "Проверка связи…";
  try {
    const r = await api("/api/config/test", { method: "POST" });
    if (r.ok) {
      st.textContent =
        "Связь OK" +
        (r.reply ? ": " + r.reply : "") +
        (r.model ? " (модель: " + r.model + ")" : "");
      toast("Связь с моделью установлена");
    } else {
      st.textContent = "Ошибка связи: " + (r.error || "нет ответа");
      toast("Модель недоступна", true);
    }
  } catch (e) {
    st.textContent = "Ошибка: " + e.message;
    toast(e.message, true);
  }
}

export function initTopics() {
  $("#refresh-topics").addEventListener("click", () => loadTopics());

  $("#form-topic").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = e.target.name.value.trim();
    const tag = e.target.tag.value.trim();
    const description = e.target.description.value.trim();
    const sched = e.target.schedule_minutes.value.trim();
    try {
      await api("/api/topics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          tag,
          description,
          schedule_minutes: sched ? parseInt(sched, 10) : 1440,
        }),
      });
      toast("Тема создана, агент запущен");
      e.target.reset();
      loadTopics();
    } catch (err) {
      toast(err.message, true);
    }
  });

  const cfgSave = document.getElementById("config-save");
  const cfgTest = document.getElementById("config-test");
  if (cfgSave) cfgSave.addEventListener("click", saveConfig);
  if (cfgTest) cfgTest.addEventListener("click", testConfig);

  $("#topic-back").addEventListener("click", () => {
    $("#topic-detail").classList.add("hidden");
    $("#topics-card").classList.remove("hidden");
    $("#topic-create-card").classList.remove("hidden");
    loadTopics();
  });
  $("#topic-run").addEventListener("click", () => runTopicAgent(state.currentTopic));
  $("#topic-reset").addEventListener("click", async () => {
    try {
      const r = await api(
        `/api/topics/reset?name=${encodeURIComponent(state.currentTopic)}`,
        { method: "POST" }
      );
      toast(
        `Исключения сняты (${r.removed || 0}) — запустите агента, чтобы собрать посты снова`
      );
    } catch (e) {
      toast(e.message, true);
    }
  });
}
