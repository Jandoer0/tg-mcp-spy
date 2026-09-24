// Общее состояние вкладок (общий источник правды между модулями).

export const state = {
  currentSource: "", // "" = все подписки
  currentKind: "", // "" = все типы, "telegram" / "rss"
  currentTags: [], // [] = без фильтра по тегам (несколько — логическое И)
  allTopics: [], // список тем (для выпадающего меню тегов и «＋»)
  currentTopic: "", // открытая тема
  // Пагинация ленты (бесконечная прокрутка).
  postsLimit: 50,
  postsOffset: 0,
  postsHasMore: true,
  postsLoading: false,
};
