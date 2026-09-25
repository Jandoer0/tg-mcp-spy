// Вкладка «Мои темы»: список тем, запуск агента, настройки провайдера.
// Кнопка «открыть в ленте» перенаправляет во вкладку «Лента новостей»
// с включённым фильтром по тегу темы (детальное окно темы убрано).

import { $, api, escapeHtml, formatTs, renderBody, toast } from "./core.js";
import { state } from "./state.js";
import { buildPostEl } from "./components.js";
import { populateTagFilter } from "./posts.js";
import { switchTab } from "./nav.js";

export async function loadAllTopics() {
  try {
    state.allTopics = await api("/api/topics");
  } catch (_e) {
    state.allTopics = [];
  }
  populateTagFilter();
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
      el.dataset.name = t.name;
      const active = t.active ? "активна" : "выкл.";
      el.innerHTML = `
        <div class="t-top">
          <span class="t-name">${escapeHtml(t.name)}</span>
          <span class="t-tag">тег: ${escapeHtml(t.tag)}</span>
          <span class="t-meta">${active} · <span class="t-count">постов: ${t.posts_count || 0}</span><br>${
        t.last_run_at ? "запуск: " + escapeHtml(formatTs(t.last_run_at, state.timezone)) : "ещё не запускался"
      }</span>
        </div>
        ${t.description ? `<div class="t-desc">${escapeHtml(t.description)}</div>` : ""}
        <div class="t-actions">
          <button class="link" data-open="${escapeHtml(t.name)}" data-tag="${escapeHtml(t.tag)}">открыть в ленте</button>
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
      .forEach((b) => b.addEventListener("click", () => openTopicInLenta(b.dataset.tag)));
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

export async function openTopicInLenta(tag) {
  // Перейти на вкладку «Лента новостей» с фильтром по тегу темы.
  state.currentTags = tag ? [tag] : [];
  state.currentSource = "";
  state.currentKind = "";
  switchTab("posts"); // populateTagFilter + loadPosts учтут выбранный тег
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
    // Часовой пояс для отображения времени (пусто = локальное время браузера).
    state.timezone = (cfg && cfg.timezone) || "";
    populateTimezones();
    const tzSel = document.getElementById("cfg-timezone");
    if (tzSel) tzSel.value = state.timezone || "";
    // Подгрузить список моделей по сохранённому адресу (если он задан).
    await fetchModels(false);
    const modelSel = document.getElementById("cfg-model");
    if (modelSel && cfg.model) modelSel.value = cfg.model;
  } catch (_e) {
    /* конфиг недоступен — поля останутся пустыми */
  }
}

// Заполнить <select> часовых поясов (один раз).
function populateTimezones() {
  const sel = document.getElementById("cfg-timezone");
  if (!sel || sel.options.length) return;
  const common = [
    "UTC", "Europe/Kaliningrad", "Europe/Moscow", "Europe/Kiev",
    "Europe/Berlin", "Europe/London",
    "Asia/Yekaterinburg", "Asia/Novosibirsk", "Asia/Krasnoyarsk",
    "Asia/Irkutsk", "Asia/Vladivostok", "Asia/Sakhalin", "Asia/Magadan",
    "Asia/Almaty", "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata",
    "Australia/Sydney", "America/New_York", "America/Los_Angeles",
  ];
  const browserTz = (Intl.DateTimeFormat().resolvedOptions().timeZone) || "";
  const opts = [{ v: "", label: "Авто (время браузера)" }];
  const seen = new Set([""]);
  if (browserTz && !common.includes(browserTz)) {
    opts.push({ v: browserTz, label: `Браузер — ${browserTz}` });
    seen.add(browserTz);
  }
  for (const z of common) {
    if (seen.has(z)) continue;
    opts.push({ v: z, label: z });
  }
  sel.innerHTML = opts
    .map((o) => `<option value="${escapeHtml(o.v)}">${escapeHtml(o.label)}</option>`)
    .join("");
}

// Опросить провайдера и заполнить <datalist> моделями.
// notify=true — показать статус (при нажатии кнопки), иначе тихо.
async function fetchModels(notify = true) {
  const card = document.getElementById("provider-card");
  const st = document.getElementById("config-status");
  const baseUrl = card.querySelector("[name=baseUrl]").value.trim();
  const apiKey = card.querySelector("[name=apiKey]").value.trim();
  if (!baseUrl) {
    if (notify) st.textContent = "Сначала укажите адрес провайдера (API URL).";
    return;
  }
  if (notify) st.textContent = "Получаем список моделей…";
  try {
    const r = await api("/api/config/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ baseUrl, apiKey }),
    });
    const sel = document.getElementById("cfg-model");
    if (r.ok && Array.isArray(r.models) && r.models.length) {
      sel.innerHTML =
        '<option value="">— выберите модель —</option>' +
        r.models.map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join("");
      if (notify) {
        st.textContent = `Найдено моделей: ${r.models.length}. Выберите из списка.`;
        toast("Список моделей обновлён");
      }
    } else {
      sel.innerHTML = '<option value="">модели не найдены</option>';
      if (notify) st.textContent = "Модели не найдены: " + (r.error || "пусто");
    }
  } catch (e) {
    if (notify) st.textContent = "Ошибка: " + e.message;
    else console.warn("Автоподгрузка моделей не удалась:", e);
  }
}

async function saveConfig(e) {
  if (e) e.preventDefault();
  const card = document.getElementById("provider-card");
  const st = document.getElementById("config-status");
  const payload = {
    provider: "ollama",
    model: card.querySelector("[name=model]").value.trim(),
    providers: {
      ollama: {
        baseUrl: card.querySelector("[name=baseUrl]").value.trim(),
        apiKey: card.querySelector("[name=apiKey]").value.trim() || "ollama",
      },
    },
  };
  try {
    await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    st.className = "config-status ok";
    st.textContent = "Сохранено. Применяется сразу (перезапуск не нужен).";
    toast("Настройки провайдера сохранены");
  } catch (e) {
    st.className = "config-status err";
    st.textContent = "Ошибка: " + e.message;
    toast(e.message, true);
  }
}

async function testConfig() {
  const st = document.getElementById("config-status");
  st.textContent = "Проверка связи…";
  try {
    const r = await api("/api/config/test", { method: "POST" });
    if (r.ok) {
      st.className = "config-status ok";
      st.textContent = r.message || `Связь установлена. Модель ${r.model || ""} активна.`;
      toast("Связь с моделью установлена");
    } else {
      st.className = "config-status err";
      st.textContent = "Ошибка связи: " + (r.error || "нет ответа");
      toast("Модель недоступна", true);
    }
  } catch (e) {
    st.className = "config-status err";
    st.textContent = "Ошибка: " + e.message;
    toast(e.message, true);
  }
}

// Обновить ТОЛЬКО счётчик найденных постов в каждой теме — без перерисовки
// списка и без запуска агента (и без затрагивания фильтра тегов ленты).
// Тихое обновление счётчика (silent=true — без кнопки и тоста, для поллинга).
export async function refreshTopicCounts(silent = false) {
  const btn = document.getElementById("refresh-topics");
  const label = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Обновление…";
  }
  try {
    const topics = await api("/api/topics");
    const byName = {};
    for (const t of topics) byName[t.name] = t;
    document.querySelectorAll("#topics .topic").forEach((card) => {
      const t = byName[card.dataset.name];
      if (!t) return;
      const c = card.querySelector(".t-count");
      if (c) c.textContent = `постов: ${t.posts_count || 0}`;
    });
    if (!silent) toast("Счётчики найденных постов обновлены");
  } catch (e) {
    if (!silent) toast(e.message, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = label;
    }
  }
}

// Динамический счётчик: опрашиваем /api/topics раз в 5с, пока открыта
// вкладка «Мои темы» (кнопка «Обновить» убрана — обновление автоматическое).
let _topicsPollTimer = null;
export function startTopicsPolling() {
  stopTopicsPolling();
  _topicsPollTimer = setInterval(() => refreshTopicCounts(true), 5000);
}
export function stopTopicsPolling() {
  if (_topicsPollTimer) {
    clearInterval(_topicsPollTimer);
    _topicsPollTimer = null;
  }
}

export function initTopics() {
  // Кнопка «Обновить» убрана: счётчик обновляется автоматически (поллинг 5с).

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

  const cfgForm = document.getElementById("form-provider");
  const cfgTest = document.getElementById("config-test");
  if (cfgForm) cfgForm.addEventListener("submit", saveConfig);
  // «Проверить соединение» теперь и проверяет связь, и подгружает список моделей.
  if (cfgTest)
    cfgTest.addEventListener("click", async () => {
      await testConfig();
      await fetchModels(true);
    });

  // Отдельная карточка «Настройка часового пояса».
  const tzForm = document.getElementById("form-timezone");
  const tzStatus = document.getElementById("tz-status");
  if (tzForm)
    tzForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const tz = tzForm.querySelector("[name=timezone]").value || "";
      try {
        await api("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ timezone: tz }),
        });
        state.timezone = tz;
        tzStatus.className = "config-status ok";
        tzStatus.textContent = "Сохранено. Применяется сразу.";
        toast("Часовой пояс сохранён");
      } catch (err) {
        tzStatus.className = "config-status err";
        tzStatus.textContent = "Ошибка: " + err.message;
        toast(err.message, true);
      }
    });

  // Подстраховка: заполнить <select> часовых поясов при загрузке (карточка
  // может находиться во вкладке, которая ещё не открывалась).
  populateTimezones();
}

// ----- ИИ-редактор (глобальная/пакетная обработка) -----
export function initEditorCard() {
  const form = document.getElementById("form-editor");
  const status = document.getElementById("editor-status");
  if (!form || form.dataset.wired) return;
  form.dataset.wired = "1";
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const scope = parseInt(form.querySelector("[name=scope]").value, 10) || 0;
    if (status) {
      status.className = "config-status";
      status.textContent = "ИИ-редактор запущен, обработка в фоне…";
    }
    try {
      const r = await api("/api/editor/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days: scope }),
      });
      toast(r.message || "ИИ-редактор запущен");
      if (status) {
        status.className = "config-status ok";
        status.textContent = "Запущено. Готово — обновите ленту новостей, чтобы увидеть результат.";
      }
    } catch (err) {
      toast(err.message, true);
      if (status) {
        status.className = "config-status err";
        status.textContent = "Ошибка: " + err.message;
      }
    }
  });
}
