"""Веб-страница админ-панели (ТЗ 2.1, 14.1): отдаётся без данных, все действия — через API с кодом 2FA."""


def test_admin_page_is_served_without_data(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Satti Admin" in r.text
    # в самой странице нет ни токенов, ни данных магазинов
    assert "Bearer " not in r.text.split("<script>")[0]
    assert "X-Admin-Code" in r.text  # код 2FA уходит с каждым административным запросом
