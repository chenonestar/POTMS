/**
 * 手写签名采集组件
 *
 * 设计要点：
 * 1. SignatureSource 抽象 —— 当前实现 CanvasPointerSource（鼠标/触摸/手写板/触摸型签批屏），
 *    将来接专有 SDK 签批屏时新增 BridgeSource 即可，业务代码不变。
 * 2. 统一输出契约 —— 三件套：PNG(dataURL) + 笔迹矢量(strokes) + 元数据(meta)。
 *    笔迹矢量使打印可按任意分辨率重绘，且换硬件后历史签名不失真。
 * 3. 鼠标优化 —— 二次贝塞尔平滑 + 采样插值，把鼠标的锯齿折线变成连贯墨迹。
 *
 * 依赖：无（纯原生，内网离线可用）
 */
(function (global) {
    'use strict';

    var LOGICAL_W = 640;   // 逻辑画布宽
    var LOGICAL_H = 220;   // 逻辑画布高
    var BASE_WIDTH = 2.5;  // 无压感时的固定线宽
    var MIN_POINTS = 8;    // 少于此点数视为误触，不算有效签名

    // -----------------------------------------------------------------
    // CanvasPointerSource：基于 Pointer Events 的采集源
    // -----------------------------------------------------------------
    function CanvasPointerSource(canvas, opts) {
        opts = opts || {};
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.strokes = [];        // [[{x,y,p,t}, ...], ...]
        this.current = null;
        this.drawing = false;
        this.pointerTypes = {};   // 出现过的设备类型计数
        this.startedAt = null;
        this.onChange = opts.onChange || function () {};
        this._setupCanvas();
        this._bind();
    }

    // 高分屏：按 devicePixelRatio 放大位图，CSS 尺寸保持逻辑尺寸
    CanvasPointerSource.prototype._setupCanvas = function () {
        var dpr = global.devicePixelRatio || 1;
        this.dpr = dpr;
        this.canvas.width = LOGICAL_W * dpr;
        this.canvas.height = LOGICAL_H * dpr;
        this.canvas.style.width = '100%';
        this.canvas.style.aspectRatio = LOGICAL_W + ' / ' + LOGICAL_H;
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.ctx.lineCap = 'round';
        this.ctx.lineJoin = 'round';
        this.ctx.strokeStyle = '#111';
        this._paintBackground();
    };

    CanvasPointerSource.prototype._paintBackground = function () {
        var c = this.ctx;
        c.save();
        c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
        c.clearRect(0, 0, LOGICAL_W, LOGICAL_H);
        c.fillStyle = '#fff';
        c.fillRect(0, 0, LOGICAL_W, LOGICAL_H);
        // 签名基准线（仅屏幕引导，不进入导出图）
        c.strokeStyle = '#dee2e6';
        c.lineWidth = 1;
        c.beginPath();
        c.moveTo(30, LOGICAL_H - 45);
        c.lineTo(LOGICAL_W - 30, LOGICAL_H - 45);
        c.stroke();
        c.strokeStyle = '#111';
        c.restore();
    };

    // 屏幕坐标 → 逻辑坐标
    CanvasPointerSource.prototype._pos = function (ev) {
        var r = this.canvas.getBoundingClientRect();
        return {
            x: (ev.clientX - r.left) * (LOGICAL_W / r.width),
            y: (ev.clientY - r.top) * (LOGICAL_H / r.height)
        };
    };

    CanvasPointerSource.prototype._bind = function () {
        var self = this;
        var cv = this.canvas;
        // touch-action:none 交给 CSS，避免触屏上手势滚动抢走事件
        cv.style.touchAction = 'none';

        cv.addEventListener('pointerdown', function (ev) {
            if (ev.button !== undefined && ev.button !== 0) return; // 仅左键
            ev.preventDefault();
            cv.setPointerCapture(ev.pointerId);
            self.drawing = true;
            if (self.startedAt === null) self.startedAt = Date.now();
            var t = ev.pointerType || 'mouse';
            self.pointerTypes[t] = (self.pointerTypes[t] || 0) + 1;
            var p = self._pos(ev);
            self.current = [{ x: p.x, y: p.y, p: self._pressure(ev), t: Date.now() }];
            self.strokes.push(self.current);
            self._redraw();
        });

        cv.addEventListener('pointermove', function (ev) {
            if (!self.drawing) return;
            ev.preventDefault();
            var p = self._pos(ev);
            var last = self.current[self.current.length - 1];
            // 抖动过滤：位移过小的点丢弃，减少鼠标噪声
            if (Math.abs(p.x - last.x) < 0.7 && Math.abs(p.y - last.y) < 0.7) return;
            self.current.push({ x: p.x, y: p.y, p: self._pressure(ev), t: Date.now() });
            self._redraw();
        });

        function finish() {
            if (!self.drawing) return;
            self.drawing = false;
            // 单击未移动 → 保留为单点，渲染成圆点（签名中的点、顿笔）
            self.current = null;
            self._redraw();
            self.onChange(self.isEmpty());
        }
        // 已 setPointerCapture，笔画移出画布再松开也能收到 pointerup；
        // 故不监听 pointerleave，避免笔画被中途截断。
        cv.addEventListener('pointerup', finish);
        cv.addEventListener('pointercancel', finish);
    };

    // 压感：手写板/触控笔可用；鼠标恒为 0.5，回落到固定线宽
    CanvasPointerSource.prototype._pressure = function (ev) {
        if (ev.pointerType === 'pen' && typeof ev.pressure === 'number' && ev.pressure > 0) {
            return ev.pressure;
        }
        return 0;   // 0 表示无压感数据
    };

    // 重绘全部笔迹（含二次贝塞尔平滑）
    CanvasPointerSource.prototype._redraw = function () {
        this._paintBackground();
        for (var i = 0; i < this.strokes.length; i++) {
            this._drawStroke(this.ctx, this.strokes[i], 1);
        }
    };

    /**
     * 绘制单笔。用相邻点中点作为二次贝塞尔的端点、原始点作为控制点，
     * 得到 C1 连续的平滑曲线 —— 这是鼠标签名观感提升最大的一步。
     */
    CanvasPointerSource.prototype._drawStroke = function (ctx, pts, scale) {
        if (!pts || pts.length === 0) return;
        scale = scale || 1;

        if (pts.length === 1) {   // 单点 → 圆点
            ctx.beginPath();
            ctx.arc(pts[0].x * scale, pts[0].y * scale, (BASE_WIDTH * scale) / 2, 0, Math.PI * 2);
            ctx.fillStyle = '#111';
            ctx.fill();
            return;
        }

        ctx.beginPath();
        ctx.lineWidth = this._lineWidth(pts) * scale;
        ctx.moveTo(pts[0].x * scale, pts[0].y * scale);
        for (var i = 1; i < pts.length - 1; i++) {
            var mx = (pts[i].x + pts[i + 1].x) / 2;
            var my = (pts[i].y + pts[i + 1].y) / 2;
            ctx.quadraticCurveTo(pts[i].x * scale, pts[i].y * scale, mx * scale, my * scale);
        }
        var last = pts[pts.length - 1];
        ctx.lineTo(last.x * scale, last.y * scale);
        ctx.stroke();
    };

    // 有压感时按均值调节线宽，否则固定
    CanvasPointerSource.prototype._lineWidth = function (pts) {
        var sum = 0, n = 0;
        for (var i = 0; i < pts.length; i++) {
            if (pts[i].p > 0) { sum += pts[i].p; n++; }
        }
        if (!n) return BASE_WIDTH;
        return BASE_WIDTH * (0.5 + (sum / n));
    };

    CanvasPointerSource.prototype.undo = function () {
        this.strokes.pop();
        this._redraw();
        this.onChange(this.isEmpty());
    };

    CanvasPointerSource.prototype.clear = function () {
        this.strokes = [];
        this.current = null;
        this.startedAt = null;
        this.pointerTypes = {};
        this._redraw();
        this.onChange(this.isEmpty());
    };

    CanvasPointerSource.prototype.isEmpty = function () {
        var n = 0;
        for (var i = 0; i < this.strokes.length; i++) n += this.strokes[i].length;
        return n < MIN_POINTS;
    };

    // 笔迹包围盒（逻辑坐标）
    CanvasPointerSource.prototype._bbox = function () {
        var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (var i = 0; i < this.strokes.length; i++) {
            for (var j = 0; j < this.strokes[i].length; j++) {
                var p = this.strokes[i][j];
                if (p.x < x0) x0 = p.x;
                if (p.y < y0) y0 = p.y;
                if (p.x > x1) x1 = p.x;
                if (p.y > y1) y1 = p.y;
            }
        }
        if (x0 === Infinity) return null;
        return { x0: x0, y0: y0, x1: x1, y1: y1 };
    };

    /**
     * 导出三件套。裁掉空白边并等比缩放到目标尺寸（保持长宽比，居中留白），
     * 使「签在角落」和「签满全屏」得到一致的成品。
     * @param {number} outW 输出位图宽（打印用可传 3 倍尺寸）
     */
    CanvasPointerSource.prototype.export = function (outW) {
        if (this.isEmpty()) return null;
        outW = outW || LOGICAL_W;
        var outH = Math.round(outW * (LOGICAL_H / LOGICAL_W));

        var bb = this._bbox();
        var pad = 12;
        var bw = Math.max(bb.x1 - bb.x0, 1), bh = Math.max(bb.y1 - bb.y0, 1);
        var scale = Math.min((LOGICAL_W - pad * 2) / bw, (LOGICAL_H - pad * 2) / bh);
        scale = Math.min(scale, 2.5);   // 限制放大倍数，避免小签名被拉伸失真
        var offX = (LOGICAL_W - bw * scale) / 2 - bb.x0 * scale;
        var offY = (LOGICAL_H - bh * scale) / 2 - bb.y0 * scale;

        var off = document.createElement('canvas');
        var r = outW / LOGICAL_W;
        off.width = outW;
        off.height = outH;
        var c = off.getContext('2d');
        c.fillStyle = '#fff';
        c.fillRect(0, 0, outW, outH);
        c.lineCap = 'round';
        c.lineJoin = 'round';
        c.strokeStyle = '#111';
        c.setTransform(r, 0, 0, r, offX * r, offY * r);

        for (var i = 0; i < this.strokes.length; i++) {
            this._drawStroke(c, this.strokes[i], scale);
        }

        var types = Object.keys(this.pointerTypes);
        types.sort(function (a, b) { return this.pointerTypes[b] - this.pointerTypes[a]; }.bind(this));
        var count = 0;
        for (var k = 0; k < this.strokes.length; k++) count += this.strokes[k].length;

        return {
            png: off.toDataURL('image/png'),
            strokes: this.strokes,
            meta: {
                v: 1,
                w: LOGICAL_W,
                h: LOGICAL_H,
                pointerType: types[0] || 'unknown',
                pointerTypes: this.pointerTypes,
                strokeCount: this.strokes.length,
                pointCount: count,
                durationMs: this.startedAt ? (Date.now() - this.startedAt) : 0,
                capturedAt: new Date().toISOString()
            }
        };
    };

    // -----------------------------------------------------------------
    // 将来接专有 SDK 签批屏时在此实现 BridgeSource（ws://127.0.0.1:PORT），
    // 输出同样的 {png, strokes, meta} 契约，业务代码无需改动。
    // -----------------------------------------------------------------

    /**
     * 绑定一个签名控件。
     * @param {object} o {canvas, clearBtn, undoBtn, pngInput, metaInput, hintEl, form}
     * @returns {object} 控件句柄（含 source / commit / isEmpty）
     */
    function attach(o) {
        var src = new CanvasPointerSource(o.canvas, {
            onChange: function (empty) {
                if (o.hintEl) {
                    o.hintEl.textContent = empty ? '请在上方区域签名' : '已签名，可点「清除」重签';
                    o.hintEl.className = empty ? 'form-text text-muted' : 'form-text text-success';
                }
            }
        });
        if (o.clearBtn) o.clearBtn.addEventListener('click', function (e) { e.preventDefault(); src.clear(); });
        if (o.undoBtn) o.undoBtn.addEventListener('click', function (e) { e.preventDefault(); src.undo(); });

        // 提交前把签名写进隐藏域
        function commit() {
            var out = src.export();
            if (!out) return false;
            if (o.pngInput) o.pngInput.value = out.png;
            if (o.metaInput) {
                o.metaInput.value = JSON.stringify({ meta: out.meta, strokes: out.strokes });
            }
            return true;
        }

        if (o.form) {
            o.form.addEventListener('submit', function (ev) {
                if (!commit()) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    alert('请先手写签名后再提交。');
                }
            });
        }
        return { source: src, commit: commit, isEmpty: function () { return src.isEmpty(); } };
    }

    global.POTMSSignature = { attach: attach, CanvasPointerSource: CanvasPointerSource };
})(window);
