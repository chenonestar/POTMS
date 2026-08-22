@param int code
@param String title
@param String message
@param String hint
@param String icon
@param String color
<%-- 中文错误页，版式与 Python 版 templates/errors/404.html、500.html 一致。

   刻意不套 layout：布局里有侧边栏、会话相关的取值与数据库查询，
   而错误页最需要的恰恰是「在别的东西都坏掉时仍能渲染出来」。 --%>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${title} - 因私出国（境）人员审批管理系统</title>
    <link href="/static/vendor/bootstrap/bootstrap.min.css" rel="stylesheet">
    <link href="/static/vendor/bootstrap-icons/bootstrap-icons.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="d-flex align-items-center justify-content-center vh-100">
        <div class="text-center" style="max-width:520px;">
            <i class="bi ${icon}" style="font-size:64px;"></i>
            <h1 class="mt-3" style="font-size:64px;font-weight:800;color:${color};">${code}</h1>
            <p class="text-muted fs-5">${message}</p>
            @if(!hint.isEmpty())
            <p class="text-muted small">${hint}</p>
            @endif
            <a href="/" class="btn btn-primary mt-2"><i class="bi bi-house"></i> 返回首页</a>
        </div>
    </div>
</body>
</html>
