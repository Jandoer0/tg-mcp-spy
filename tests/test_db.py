"""Тесты репозиториев (sources / posts / topics)."""
from tg_spy.db import (
    add_source,
    add_topic,
    exclude_post,
    get_excluded_ids,
    get_posts,
    get_posts_after,
    get_tagged_posts,
    get_tagged_total,
    list_sources,
    remove_source,
    reset_exclusions,
    tag_post,
)


def test_sources_crud():
    add_source("telegram", "durov")
    add_source("rss", "lenta", "https://example.com/feed")
    names = [s["name"] for s in list_sources()]
    assert "durov" in names and "lenta" in names
    assert list_sources("telegram")[0]["name"] == "durov"
    assert remove_source("durov") is True
    assert [s["name"] for s in list_sources()] == ["lenta"]


def test_posts_flow():
    src = add_source("telegram", "c1")
    posts = [
        {"ext_id": "1", "text": "a", "date": "2026-01-01", "url": "u1"},
        {"ext_id": "2", "text": "b", "date": "2026-01-02", "url": "u2"},
    ]
    from tg_spy.db import save_posts

    save_posts(src["id"], posts)
    got = get_posts([src["id"]], "1970-01-01")
    assert len(got) == 2
    after = get_posts_after(0, 10)
    assert len(after) == 2


def test_topics_tagging_and_exclusions():
    from tg_spy.db import save_posts

    add_source("telegram", "c1")
    src = list_sources()[0]
    save_posts(src["id"], [{"ext_id": "1", "text": "x", "date": "2026-01-01", "url": "u"}])
    first_post = get_posts_after(0, 10)[0]
    post_id = first_post["id"]

    topic = add_topic("Тест", "Лада", 1440, "описание")
    tid = topic["id"]

    assert get_tagged_total(tid) == 0
    row = tag_post(tid, post_id, mode="ai")
    assert row is not None
    assert get_tagged_total(tid) == 1

    # Исключение скрывает пост из хронологии (движок не вернёт его).
    assert exclude_post(tid, post_id) is True
    assert get_tagged_total(tid) == 0
    assert post_id in get_excluded_ids(tid, [post_id, 999])

    # Сброс исключений снимает признак.
    assert reset_exclusions(tid, post_id) == 1
    assert get_excluded_ids(tid, [post_id]) == set()

    # Удаление темы каскадно чистит теги.
    from tg_spy.db import remove_topic

    assert remove_topic("Тест") is True
    assert get_tagged_posts(tid) == []
