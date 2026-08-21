// 手写签名数据解析与校验 — 对应 Python 版 blueprints/issuance.py 的
// _decode_signature / _clean_meta。
//
// 签名以 PNG 位图 + 笔迹矢量双存于数据库（BLOB/TEXT），随每日备份一起落盘；
// 不落文件系统（uploads 目录不在备份范围内，签名凭证丢了没法补签）。
package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"strings"
)

// PNG 魔数（防止前端传入非图片内容）
var pngMagic = []byte{0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A}

const (
	signPrefix = "data:image/png;base64,"
	// 单张签名上限：正常裁剪后 5–20KB，留足余量仍可拦住异常大图
	maxSignBytes = 512 * 1024
	maxMetaChars = 400_000
)

// decodeSignature 把 dataURL 解成 PNG 字节。失败时返回 (nil, 错误信息)。
//
// 留空是否算错，取决于 required（来自 POTMS_REQUIRE_SIGNATURE，默认强制）。
// 注意这里是**唯一**真正的守门人：前端那两道拦截（提交前校验、少于 8 点算误触）
// 都在浏览器里，伪造 POST 绕得过。
//
// 格式校验不受开关影响——签了就必须是合法 PNG，不能因为「不强制」就把坏数据
// 放进库里。
func decodeSignature(dataURL string, required bool) ([]byte, string) {
	raw := strings.TrimSpace(dataURL)
	if raw == "" {
		if required {
			return nil, "请手写签名后再提交。"
		}
		return nil, "" // 放宽模式：留空即无签名，记录里如实存 NULL
	}
	if !strings.HasPrefix(raw, signPrefix) {
		return nil, "签名数据格式不正确。"
	}
	payload := raw[len(signPrefix):]
	// 先按 base64 长度粗判体积再解码，避免为超大载荷先分配一遍内存
	if len(payload)/4*3 > maxSignBytes {
		return nil, "签名图像过大，请重新签名。"
	}
	blob, err := base64.StdEncoding.DecodeString(payload)
	if err != nil {
		return nil, "签名数据解析失败，请重新签名。"
	}
	if !bytes.HasPrefix(blob, pngMagic) {
		return nil, "签名数据不是有效的 PNG 图像。"
	}
	if len(blob) > maxSignBytes {
		return nil, "签名图像过大，请重新签名。"
	}
	return blob, ""
}

// cleanMeta 校验笔迹矢量 JSON；过大或非法则丢弃（不阻断业务，位图仍在）。
func cleanMeta(raw string) interface{} {
	raw = strings.TrimSpace(raw)
	if raw == "" || len(raw) > maxMetaChars {
		return nil
	}
	var probe interface{}
	if json.Unmarshal([]byte(raw), &probe) != nil {
		return nil
	}
	return raw
}
