@param java.util.List<com.potms.web.Flash.Message> flashes
@if(!flashes.isEmpty())
    <div class="mt-3">
        @for(var m : flashes)
            <div class="alert alert-${m.category()} alert-dismissible fade show" role="alert">
                ${m.text()}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="关闭"></button>
            </div>
        @endfor
    </div>
@endif
