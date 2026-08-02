@param com.potms.web.Helpers.Page<?> pg
@param String basePath
@param String query
@if(pg.pages() > 1)
    !{var qs = com.potms.web.Pager.stripPage(query);}
    <nav aria-label="Page navigation">
        <ul class="pagination justify-content-center">
            <li class="page-item ${pg.hasPrev() ? "" : "disabled"}">
                <a class="page-link" href="${pg.hasPrev() ? com.potms.web.Pager.url(basePath, qs, pg.page() - 1) : "#"}">上一页</a>
            </li>
            !{int start = Math.max(pg.page() - 2, 1); int end = Math.min(pg.page() + 2, pg.pages());}
            @if(start > 1)
                <li class="page-item"><a class="page-link" href="${com.potms.web.Pager.url(basePath, qs, 1)}">1</a></li>
                @if(start > 2)<li class="page-item disabled"><span class="page-link">…</span></li>@endif
            @endif
            @for(int p = start; p <= end; p++)
                <li class="page-item ${p == pg.page() ? "active" : ""}">
                    <a class="page-link" href="${com.potms.web.Pager.url(basePath, qs, p)}">${p}</a>
                </li>
            @endfor
            @if(end < pg.pages())
                @if(end < pg.pages() - 1)<li class="page-item disabled"><span class="page-link">…</span></li>@endif
                <li class="page-item"><a class="page-link" href="${com.potms.web.Pager.url(basePath, qs, pg.pages())}">${pg.pages()}</a></li>
            @endif
            <li class="page-item ${pg.hasNext() ? "" : "disabled"}">
                <a class="page-link" href="${pg.hasNext() ? com.potms.web.Pager.url(basePath, qs, pg.page() + 1) : "#"}">下一页</a>
            </li>
        </ul>
    </nav>
    <div class="text-center text-muted small">共 ${pg.total()} 条记录，第 ${pg.page()}/${pg.pages()} 页</div>
@endif
