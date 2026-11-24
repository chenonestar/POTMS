"""第 14 批：框架默认页再也逃不出去。

此前只注册了 404 / 413 / 500 三个处理器，**没有专页的状态码一律走 werkzeug
默认页**：英文、没有导航、整页替换。逐个实测过：

    405  ✗ 框架默认页   真实可达
    400  ✗ 框架默认页   非 CSRF 的那一支（`return err`）
    403  ✗ 框架默认页   目前无调用点，但那一支敞着
    401  ✗ 框架默认页   同上

**405 是真会撞到的那个。** 系统里有 21 条 POST-only 路由，全是动作类：删除、
取消、恢复、作废、撤销撤控、备份、字典与组织机构增删。地址栏手输、收藏一个
动作地址、对提交完的页面按刷新，都会撞上。

按通行做法，405 本该留默认页——前提是「有开发者会看见这个难看的页面并去修
链接」。这套系统是单机内网、无错误监控、没人读日志，**没有这个人**；唯一的
使用者是读不了英文的操作员。而且扫过全部模板：没有任何 `<a href>` 或
`data-action` 指向那 21 条路由，也就是说系统自己不会制造 405——它只可能由
操作员手输/收藏/刷新产生，而那时他最急的问题不是「这页怎么是英文」，是
**「我刚才是不是把东西删了」**。这个问题只有一张中文页能回答。

所以不一条条补，补根：注册一个 `HTTPException` 处理器。Flask 查处理器时
**先按状态码找，找不到再按异常类的 MRO 找**，所以 404 / 413 / 500 仍走各自
专页，其余一律落到通用页。保证的不是「这三个补上了」，而是**下次冒出个
409、422 同样接得住**。

顺带拆掉一个陷阱：`utils/csrf.py` 原先注册了 400 处理器，里面有一支
`return err`（非 CSRF 的 400 原样返回 = 英文默认页）。改成 `_csrf_protect`
直接返回重定向，整个 400 处理器删掉——少一个处理器，少一条要维护的判据。
"""
import re
import sqlite3

import pytest
from flask import abort

from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
# werkzeug 默认错误页的特征：doctype 之后紧跟不带引号的 <html lang=en>。
# 本系统的页面一律是 <html lang="zh-CN">。
_DEFAULT_PAGE = "<html lang=en>"


def _app(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()
    from app import create_app
    app = create_app()

    # 几条专门用来抛错的路由。必须在第一次请求之前挂上，否则 Flask 拒绝注册。
    # 403 / 401 / 409 在产品代码里目前都没有调用点——但那几支敞着，
    # 迟早有人用上，所以现在就把它们钉住。
    @app.route("/__400")
    def _f400(): abort(400, description="参数格式不正确")
    @app.route("/__401")
    def _f401(): abort(401)
    @app.route("/__403")
    def _f403(): abort(403)
    @app.route("/__409")
    def _f409(): abort(409)
    @app.route("/__boom")
    def _boom(): raise RuntimeError("boom")
    return app


@pytest.fixture()
def cl(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    c = app.test_client()
    tok = _CSRF.search(c.get("/login").get_data(as_text=True)).group(1)
    c.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return c


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


# 每一项：(说明, 取页面的函数, 期望状态码)
def _cases(cl):
    return [
        ("404 不存在的路径",       lambda: cl.get("/nope"),                                 404),
        ("405 GET 一个 POST 路由", lambda: cl.get("/travel/1/delete"),                      405),
        ("405 POST 一个 GET 路由", lambda: cl.post("/travel/", data={"csrf_token": _tok(cl)}), 405),
        ("400 非 CSRF 的 abort",   lambda: cl.get("/__400"),                                400),
        ("401 abort(401)",         lambda: cl.get("/__401"),                                401),
        ("403 abort(403)",         lambda: cl.get("/__403"),                                403),
        ("409 没写文案的码",       lambda: cl.get("/__409"),                                409),
        ("500 未捕获异常",         lambda: cl.get("/__boom"),                               500),
    ]


# ===========================================================================
# 一、一个都不许漏
# ===========================================================================
def test_no_status_code_falls_through_to_the_framework_page(cl):
    """八个能到达的状态码，一个都不许回 werkzeug 默认页。

    这是整批的主断言。它不逐个点名「405 修了」，而是把能到达的码摆成一张表
    整体过一遍——摆表这个动作本身就是发现方法（见清单第 20 条）。
    """
    leaked = []
    for name, fn, want in _cases(cl):
        r = fn()
        body = r.get_data(as_text=True)
        assert r.status_code == want, f"{name}：状态码是 {r.status_code}，期望 {want}"
        if _DEFAULT_PAGE in body:
            leaked.append(name)
    assert not leaked, f"这些还在回框架默认页：{leaked}"


def test_every_error_page_is_ours_and_in_chinese(cl):
    """每一页都要是本系统的页面：带站点标题、中文、有返回首页的出口。"""
    for name, fn, _ in _cases(cl):
        body = fn().get_data(as_text=True)
        assert "因私出国（境）人员审批管理系统" in body, f"{name} 不是本系统的页面"
        assert '<html lang="zh-CN">' in body, f"{name} 不是中文页"
        assert "返回首页" in body, f"{name} 没给返回首页的出口"


def test_the_fallback_handler_is_registered_for_the_exception_class(cl):
    """兜底处理器要挂在 HTTPException 类上，而不是逐个状态码。

    挂在类上才有「下次冒出个 409、422 同样接得住」这个性质。逐个注册的话
    这条用例会红——而上面那张表里恰好有一个 409 就是为此准备的。
    """
    from werkzeug.exceptions import HTTPException
    spec = cl.application.error_handler_spec[None]
    assert HTTPException in (spec.get(None) or {}), "没有按异常类注册兜底处理器"
    # 三个专页仍按状态码注册，不能被兜底处理器顶掉
    for code in (404, 413, 500):
        assert spec.get(code), f"{code} 的专页处理器没了"


def test_the_dedicated_pages_still_win(cl):
    """404 / 413 / 500 仍走各自专页，不被通用页顶掉。

    Flask 先按状态码找处理器、找不到才按异常类的 MRO 找。这条用例钉的就是
    这个顺序——顺序一反，三张写好的专页就白费了。
    """
    assert "您访问的页面不存在或已被移除" in cl.get("/nope").get_data(as_text=True)
    assert "系统内部错误" in cl.get("/__boom").get_data(as_text=True)


# ===========================================================================
# 二、405 的文案：要回答「我刚才是不是把东西删了」
# ===========================================================================
def test_the_405_page_says_the_action_was_not_executed(cl):
    """这是 405 页面存在的理由。

    那 21 条 POST-only 路由全是删除 / 取消 / 恢复 / 作废 / 备份这类动作。
    撞上 405 的人最急的不是「这页怎么是英文」，而是「我刚才是不是把东西
    删了」。只说「方法不允许」等于没回答。
    """
    body = cl.get("/travel/1/delete").get_data(as_text=True)
    assert "这个地址不能直接打开" in body
    assert "没有被执行" in body and "数据没有任何改动" in body


def test_the_405_page_tells_the_operator_what_to_do_instead(cl):
    """还要说清正确做法：回列表页用那一行上的按钮。"""
    body = cl.get("/travel/1/delete").get_data(as_text=True)
    assert "按钮" in body and "列表" in body


def test_no_page_echoes_werkzeug_english_description(cl):
    """不许把 werkzeug 自带的 description 打到页面上。

    那是英文的通用句子（405 是 "The method is not allowed for the requested
    URL."）。透传它等于把英文又搬回来了，只是外面套了个中文框——这是通用
    错误页最容易写错的地方：查不到中文文案时顺手 `err.description or ...`，
    「至少说点什么」。

    **句子是向 werkzeug 要的，不是我列的。** 第一版凭记忆列了六个英文片段
    （"Unauthorized" / "Forbidden" / "Conflict" …），撤销验证时把默认文案换成
    `err.description` —— 用例全绿。实际 description 里这三个词一个都没有：
    401 写的是 "could not verify"、403 是 "don't have the permission"、
    409 是 "A conflict happened while processing"。五个码里只碰巧覆盖了两个。
    改成从 default_exceptions 取，断言就与我记得什么无关，也自动覆盖以后
    新冒出来的码。
    """
    from werkzeug.exceptions import default_exceptions
    for name, fn, code in _cases(cl):
        body = fn().get_data(as_text=True)
        desc = default_exceptions[code]().description or ""
        assert desc not in body, f"{name} 里原样透传了 werkzeug 的英文说明"
        # 截一段再拼也算透传，取开头一句钉住
        assert desc[:40] not in body, f"{name} 里透传了 werkzeug 英文说明的开头"


def test_the_500_page_does_not_leak_the_exception(cl):
    """500 页面不许带异常细节。写通用页时最容易顺手把 err 打出来。"""
    body = cl.get("/__boom").get_data(as_text=True)
    assert "boom" not in body
    assert "RuntimeError" not in body and "Traceback" not in body


# ===========================================================================
# 三、CSRF 那条路没被改坏
# ===========================================================================
def test_csrf_failure_still_redirects_to_login(cl):
    """CSRF 失败仍然引导重新登录，不是停在错误页。

    改法是让 _csrf_protect 直接返回重定向，而不再 abort(400)——为的是能把
    那个带着 `return err` 的 400 处理器整个删掉。行为必须保持不变。
    """
    r = cl.post("/travel/new", data={})
    assert r.status_code == 302
    assert "/login" in (r.headers.get("Location") or "")


def test_there_is_no_400_handler_left_to_leak(cl):
    """400 不再有自己的处理器，统一落到兜底页。

    原先那个处理器里的 `return err` 是个装好了的陷阱：谁写一句
    abort(400, "参数不对")，当场就是一屏英文。少一个处理器，少一条判据。
    """
    assert not cl.application.error_handler_spec[None].get(400), \
        "400 又有自己的处理器了，当心那条 return err 的老路"
    body = cl.get("/__400").get_data(as_text=True)
    assert "请求无法识别" in body and _DEFAULT_PAGE not in body


def test_a_normal_request_is_untouched(cl):
    """反向对照：正常页面照常返回 200，别把兜底处理器写成了拦一切。"""
    r = cl.get("/travel/")
    assert r.status_code == 200
    assert "出国（境）申请列表" in r.get_data(as_text=True)


# ===========================================================================
# 四、兜底不能自己成为错误源
# ===========================================================================
def test_the_fallback_survives_a_missing_template(cl, monkeypatch):
    """模板找不到时退回纯文本，而不是把一个 405 升级成 500。

    打包成单文件 exe 时 PyInstaller 把资源解压到 %TEMP%\\_MEIxxxx，程序退出
    即删。服务进程比那个目录活得久时模板会一起消失——渲染错误页抛
    TemplateNotFound，一个 405 就变成 500，500 处理器再抛一次，最后由
    waitress 打出整屏堆栈。_error_page 那个 try/except 就是为此。
    新加的通用页必须也走那条路，不能自己 render_template。
    """
    from jinja2 import TemplateNotFound

    # 直接让 Jinja 找不到模板，而不是替换 render_template——app.py 第 85 行把
    # render_template **import 进了 create_app 的局部作用域**，_error_page 闭包
    # 捕获的是那个局部名字，patch flask.render_template 根本碰不到它（第一版就
    # 这么写的，用例红了才发现）。改成摘掉 loader，也更接近 _MEI 目录被删的真相。
    def _gone(*a, **k):
        raise TemplateNotFound(a[0] if a else "?")
    monkeypatch.setattr(cl.application.jinja_env, "get_or_select_template", _gone)

    r = cl.get("/travel/1/delete")
    assert r.status_code == 405, "模板丢了之后状态码被改掉了"
    assert "text/plain" in r.headers.get("Content-Type", ""), \
        "模板丢了之后没有退回纯文本，可能升级成了 500"
    assert "405" in r.get_data(as_text=True)
