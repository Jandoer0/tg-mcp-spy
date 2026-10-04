// Вкладка «Мои темы»: список тем, запуск агента, настройки провайдеров ИИ.
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

// ----- Настройки провайдеров ИИ (единая логика для обеих ролей) -----
//
// У «ИИ классификатора» и «ИИ редактора» СВОИ конфигурации провайдеров
// (можно держать классификатор на локальной модели, а редактор — у
// облачного провайдера), но логика работы и оповещения одинаковые:
// сохранение, проверка соединения и загрузка списка моделей идут через
// одни и те же функции ниже — роль меняет только набор настроек.

const ROLES = {
  classifier: {
    cardId: "classifier-card",
    formId: "form-provider",
    baseUrlSel: "[name=baseUrl]",
    apiKeySel: "[name=apiKey]",
    modelId: "cfg-model",
    promptSel: "[name=systemPrompt]",
    promptKey: "systemPrompt",
    statusId: "config-status",
    testBtnId: "config-test",
  },
  editor: {
    cardId: "editor-card",
    formId: "form-editor",
    baseUrlSel: "#editor-baseUrl",
    apiKeySel: "#editor-apiKey",
    modelId: "editor-model",
    promptSel: "[name=editorSystemPrompt]",
    promptKey: "editorSystemPrompt",
    statusId: "editor-status",
    testBtnId: "editor-test",
  },
};

// Элементы карточки роли (одинаковый набор полей у обеих ролей).
function roleEls(role) {
  const r = ROLES[role];
  const card = document.getElementById(r.cardId);
  if (!card) return null;
  return {
    card,
    form: document.getElementById(r.formId),
    baseUrl: card.querySelector(r.baseUrlSel),
    apiKey: card.querySelector(r.apiKeySel),
    model: document.getElementById(r.modelId),
    prompt: card.querySelector(r.promptSel),
    status: document.getElementById(r.statusId),
  };
}

// Тело POST /api/config для одной роли (провайдер + модель + промпт).
function rolePayload(role) {
  const els = roleEls(role);
  const r = ROLES[role];
  return {
    [role]: {
      provider: {
        baseUrl: els.baseUrl ? els.baseUrl.value.trim() : "",
        apiKey: els.apiKey ? els.apiKey.value.trim() || "ollama" : "ollama",
      },
      model: els.model ? els.model.value.trim() : "",
    },
    [r.promptKey]: els.prompt ? els.prompt.value : "",
  };
}

// Статус в карточке роли — одинаковые классы и тексты для обеих ролей.
function setRoleStatus(role, text, ok = null) {
  const els = roleEls(role);
  if (!els || !els.status) return;
  els.status.className =
    "config-status" + (ok === true ? " ok" : ok === false ? " err" : "");
  els.status.textContent = text;
}

// Сохранить настройки роли на сервер (одинаковые оповещения для обеих).
async function saveRoleConfig(role) {
  try {
    await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rolePayload(role)),
    });
    setRoleStatus(role, "Сохранено. Применяется сразу.", true);
    toast("Настройки ИИ сохранены");
  } catch (e) {
    setRoleStatus(role, "Ошибка: " + e.message, false);
    toast(e.message, true);
  }
}

// «Проверить соединение» — проверяет значения из формы роли до сохранения
// (baseUrl/apiKey передаются в теле; бэкенд использует настройки роли).
async function testRoleConnection(role) {
  const els = roleEls(role);
  if (!els) return;
  const baseUrl = els.baseUrl ? els.baseUrl.value.trim() : "";
  if (!baseUrl) {
    setRoleStatus(role, "Сначала укажите адрес провайдера (API URL).", false);
    return;
  }
  const apiKey = els.apiKey ? els.apiKey.value.trim() : "";
  setRoleStatus(role, "Проверка связи…");
  try {
    const r = await api("/api/config/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: role, baseUrl, apiKey }),
    });
    if (r.ok) {
      setRoleStatus(role, r.message || `Связь установлена. Модель ${r.model || ""} активна.`, true);
      toast("Связь с моделью установлена");
    } else {
      setRoleStatus(role, "Ошибка связи: " + (r.error || "нет ответа"), false);
      toast("Модель недоступна", true);
    }
  } catch (e) {
    setRoleStatus(role, "Ошибка: " + e.message, false);
    toast(e.message, true);
  }
}

// Опросить провайдер и заполнить <select> моделями роли (общая логика).
// notify=true — показать статус (при нажатии кнопки), иначе тихо.
// desiredModel — модель из конфига, которую нужно выбрать после обновления
// списка (при начальной загрузке). Если не задана — сохраняем текущий выбор.
async function fetchRoleModels(role, notify = true, desiredModel = null) {
  const els = roleEls(role);
  if (!els || !els.model) return;
  const baseUrl = els.baseUrl ? els.baseUrl.value.trim() : "";
  const apiKey = els.apiKey ? els.apiKey.value.trim() : "";
  if (!baseUrl) {
    if (notify) setRoleStatus(role, "Сначала укажите адрес провайдера (API URL).", false);
    return;
  }
  if (notify) setRoleStatus(role, "Получаем список моделей…");
  const sel = els.model;
  const prev = sel.value;
  try {
    const r = await api("/api/config/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ baseUrl, apiKey, type: role }),
    });
    if (r.ok && Array.isArray(r.models) && r.models.length) {
      // Модель из конфига/переменной окружения всегда остаётся в списке,
      // даже если провайдер её сейчас не отдаёт (например, не загружена в Ollama).
      const list = desiredModel && !r.models.includes(desiredModel)
        ? [desiredModel, ...r.models]
        : r.models;
      sel.innerHTML =
        '<option value="">— выберите модель —</option>' +
        list.map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join("");
      const target = desiredModel || prev;
      if (target && list.includes(target)) sel.value = target;
      if (notify) {
        setRoleStatus(role, `Найдено моделей: ${r.models.length}. Текущая: ${sel.value || "—"}.`, true);
        toast("Список моделей обновлён");
      }
    } else {
      // Провайдер не вернул модели — сохраняем текущую (env) модель видимой.
      if (desiredModel) {
        sel.innerHTML =
          '<option value="">— выберите модель —</option>' +
          `<option value="${escapeHtml(desiredModel)}">${escapeHtml(desiredModel)}</option>`;
        sel.value = desiredModel;
      } else {
        sel.innerHTML = '<option value="">модели не найдены</option>';
      }
      if (notify) {
        setRoleStatus(
          role,
          "Модели не найдены: " + (r.error || "пусто") +
            (desiredModel ? ` (используется ${desiredModel})` : ""),
          false
        );
      }
    }
  } catch (e) {
    // Ошибка сети/провайдера — не теряем текущую (env) модель, оставляем её видимой.
    if (desiredModel) {
      sel.innerHTML =
        '<option value="">— выберите модель —</option>' +
        `<option value="${escapeHtml(desiredModel)}">${escapeHtml(desiredModel)}</option>`;
      sel.value = desiredModel;
    }
    if (notify) setRoleStatus(role, "Ошибка: " + e.message, false);
    else console.warn("Автоподгрузка моделей не удалась:", e);
  }
}

export async function loadConfig() {
  try {
    const cfg = await api("/api/config");

    // Настройки обеих ролей — симметрично: провайдер + модель + промпт.
    for (const role of Object.keys(ROLES)) {
      const els = roleEls(role);
      if (!els) continue;
      const r = ROLES[role];
      const prov = (cfg[role] && cfg[role].provider) || {};
      if (els.baseUrl) els.baseUrl.value = prov.baseUrl || "";
      if (els.apiKey) els.apiKey.value = prov.apiKey || "";
      if (els.prompt) els.prompt.value = cfg[r.promptKey] || "";
      // Модель подставляем после загрузки списка (desiredModel), т.к. <select>
      // в этот момент ещё не содержит нужных <option>.
      await fetchRoleModels(role, false, (cfg[role] && cfg[role].model) || "");
    }

    // Часовой пояс
    state.timezone = (cfg && cfg.timezone) || "";
    populateTimezones();
    const tzSel = document.getElementById("cfg-timezone");
    if (tzSel) tzSel.value = state.timezone || "";

    // Интервал обновления
    const refreshInput = document.getElementById("cfg-feed-refresh");
    if (refreshInput) {
      refreshInput.value = (cfg && cfg.schedule && cfg.schedule.feedRefreshMinutes) || 60;
    }
  } catch (e) {
    console.error("Ошибка при загрузке конфига:", e);
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

// Подключить карточки «ИИ классификатор» и «ИИ редактор» — единая логика:
// у каждой роли свой провайдер/модель, но одинаковые действия и оповещения
// (сохранить → POST /api/config; проверить → POST /api/config/test + модели).
export function initProviderCards() {
  for (const role of Object.keys(ROLES)) {
    const els = roleEls(role);
    if (!els || !els.form || els.form.dataset.wired) continue;
    els.form.dataset.wired = "1";

    // Сохранить (сабмит формы карточки — у обеих ролей одинаково).
    els.form.addEventListener("submit", (e) => {
      e.preventDefault();
      saveRoleConfig(role);
    });

    // «Проверить соединение»: проверяет связь и заодно обновляет список
    // моделей — одинаковые статусы и тосты для обеих ролей.
    const testBtn = document.getElementById(ROLES[role].testBtnId);
    if (testBtn)
      testBtn.addEventListener("click", async () => {
        await testRoleConnection(role);
        await fetchRoleModels(role, true);
      });
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

  // Отдельная карточка «Настройка часового пояса».
  const tzForm = document.getElementById("form-timezone");
  const tzStatus = document.getElementById("tz-status");
  if (tzForm)
    tzForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const tz = tzForm.querySelector("[name=timezone]").value || "";
      const refreshMin = tzForm.querySelector("[name=feedRefreshMinutes]").value || "60";
      try {
        await api("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            timezone: tz,
            schedule: {
              feedRefreshMinutes: parseInt(refreshMin, 10) || 60
            }
          }),
        });
        state.timezone = tz;
        tzStatus.className = "config-status ok";
        tzStatus.textContent = "Сохранено. Применяется сразу.";
        toast("Параметры сохранены");
      } catch (err) {
        tzStatus.className = "config-status err";
        tzStatus.textContent = "Ошибка: " + err.message;
        toast(err.message, true);
      }
    });

  // Подстраховка: заполнить <select> часовых поясов при загрузке (карточка
  // может находиться во вкладке, которая ещё не открывалась).
  populateTimezones();

  // Карточки «ИИ классификатор» и «ИИ редактор» (единая логика ролей).
  initProviderCards();

  // Переключатели «ИИ-классификатор» и «ИИ-редактор» в шапке ленты.
  // Одновременно активен только один из них (взаимоисключающие).
  const aiClassifier = document.getElementById("classifier-toggle");
  const aiEditor = document.getElementById("editor-toggle");

  // Исходное состояние из конфига.
  api("/api/config").then((cfg) => {
    const sched = (cfg && cfg.schedule) || {};
    if (aiClassifier) aiClassifier.checked = !!sched.enabled;
    if (aiEditor) aiEditor.checked = !!sched.editorEnabled;
  }).catch(() => {});

  // Сохранить режим ИИ (none | classifier | editor) в конфиг.
  async function applyAiMode(mode) {
    const schedule =
      mode === "classifier"
        ? { enabled: true, editorEnabled: false }
        : mode === "editor"
          ? { enabled: false, editorEnabled: true }
          : { enabled: false, editorEnabled: false };
    await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ schedule }),
    });
  }

  // Общий обработчик переключателя роли: одинаковый сценарий для
  // классификатора и редактора (обновить ленту → запустить обработку).
  function wireAiToggle(toggleEl, otherEl, role) {
    if (!toggleEl) return;
    toggleEl.addEventListener("change", async () => {
      const on = toggleEl.checked;
      const label = role === "classifier" ? "ИИ-классификатор" : "ИИ-редактор";
      try {
        if (on) {
          await applyAiMode(role);
          if (otherEl) otherEl.checked = false;
          try {
            await api("/api/refresh/posts", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ days: 1 }),
            });
          } catch (_e) { /* обновление ленты не критично */ }
          try {
            const runUrl =
              role === "classifier"
                ? "/api/topics/run-all"
                : "/api/editor/run";
            await api(runUrl, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({}),
            });
          } catch (_e) { /* обработка запустится по расписанию */ }
          toast(`${label} включён — модель запущена`);
        } else {
          await applyAiMode("none");
          toast(`${label} выключен`);
        }
      } catch (e) {
        toast(e.message, true);
        toggleEl.checked = !on;
      }
    });
  }

  wireAiToggle(aiClassifier, aiEditor, "classifier");
  wireAiToggle(aiEditor, aiClassifier, "editor");
}
