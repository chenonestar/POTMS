@import com.potms.service.ExcelImport
@param com.potms.web.Ctx ctx
@param ExcelImport.Result result
@template.layout(ctx = ctx, title = "批量导入", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-upload"></i> 批量导入备案人员</h4>

    <div class="alert alert-light border small text-muted py-2">
        一行同时生成「信息登记表」与「登记备案表」两条记录。逐行独立校验：某行有错只跳过该行，
        其余照常入库，报告里会列出每一行的问题，便于一次改完再传。
    </div>

    <div class="card mb-3"><div class="card-body">
        <form method="POST" action="/import" enctype="multipart/form-data" class="row g-2 align-items-end">
            <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
            <div class="col-md-6">
                <label class="form-label">选择 Excel 文件（.xlsx）</label>
                <input type="file" class="form-control" name="file" accept=".xlsx" required>
            </div>
            <div class="col-auto"><button class="btn btn-primary"><i class="bi bi-upload"></i> 开始导入</button></div>
            <div class="col-auto"><a href="/import/template" class="btn btn-outline-secondary"><i class="bi bi-download"></i> 下载模板</a></div>
        </form>
    </div></div>

    @if(result != null)
        <div class="card mb-4">
            <div class="card-header">
                导入报告 ——
                共 <strong>${result.total()}</strong> 条，
                成功 <strong class="text-success">${result.success()}</strong> 条，
                失败 <strong class="text-danger">${result.failedRows()}</strong> 条
                （${result.errors().size()} 处问题）
            </div>
            @if(result.errors().isEmpty())
                <div class="card-body text-success small"><i class="bi bi-check-circle"></i> 全部导入成功。</div>
            @else
                <div class="table-responsive">
                    <table class="table table-sm mb-0">
                        <thead class="table-light"><tr><th style="width:110px">Excel 行号</th><th style="width:180px">字段</th><th>问题</th></tr></thead>
                        <tbody>
                        @for(var e : result.errors())
                            <tr><td>第 ${e.row()} 行</td><td>${e.field()}</td><td class="text-danger">${e.message()}</td></tr>
                        @endfor
                        </tbody>
                    </table>
                </div>
            @endif
        </div>
    @endif
`)
