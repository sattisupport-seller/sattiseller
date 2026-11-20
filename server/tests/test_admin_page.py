"""Веб-страница админ-панели (ТЗ 2.1, 14.1): отдаётся без данных, все действия — через API с кодом 2FA."""


def test_admin_page_is_served_without_data(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Satti Admin" in r.text
    # в самой странице нет ни токенов, ни данных магазинов
    assert "Bearer " not in r.text.split("<script>")[0]
    assert '<script src="/admin.js">' in r.text
    script = client.get("/admin.js").text
    assert "X-Admin-Session" in script  # код 2FA меняется на сессию (AUD-15), а не уходит с каждым запросом
    assert "X-Admin-Code" not in script and "X-Admin-Code" not in r.text


def test_admin_script_is_a_file_and_csp_forbids_inline_scripts(client):
    js = client.get("/admin.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("application/javascript")
    csp = client.get("/admin").headers["content-security-policy"]
    script_src = [d for d in csp.split(";") if d.strip().startswith("script-src")][0]
    assert "unsafe-inline" not in script_src
    assert "'self'" in script_src
