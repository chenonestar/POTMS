//! 手写签名数据解析与校验 —— 对应 Python 版 blueprints/issuance.py 的
//! `_decode_signature` / `_clean_meta`。
//!
//! 签名以 PNG 位图 + 笔迹矢量双存于数据库（BLOB/TEXT），随每日备份一起落盘；
//! 不落文件系统（uploads 目录不在备份范围内，签名凭证丢了没法补签）。

use base64::{engine::general_purpose::STANDARD as B64, Engine};

/// PNG 魔数（防止前端传入非图片内容）
const PNG_MAGIC: &[u8] = &[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];
const PREFIX: &str = "data:image/png;base64,";
/// 单张签名上限：正常裁剪后 5–20KB，留足余量仍可拦住异常大图
pub const MAX_SIGN_BYTES: usize = 512 * 1024;
pub const MAX_META_CHARS: usize = 400_000;

/// dataURL → PNG 字节。失败时返回 `Err(错误信息)`；放宽模式下留空返回 `Ok(None)`。
///
/// 留空是否算错，取决于 `required`（来自 POTMS_REQUIRE_SIGNATURE，默认强制）。
/// 注意这里是**唯一**真正的守门人：前端那两道拦截（提交前校验、少于 8 点算误触）
/// 都在浏览器里，伪造 POST 绕得过。
///
/// 格式校验不受开关影响——签了就必须是合法 PNG，不能因为「不强制」就把坏数据
/// 放进库里。
pub fn decode(data_url: &str, required: bool) -> Result<Option<Vec<u8>>, String> {
    let raw = data_url.trim();
    if raw.is_empty() {
        return if required {
            Err("请手写签名后再提交。".into())
        } else {
            Ok(None) // 放宽模式：留空即无签名，记录里如实存 NULL
        };
    }
    let payload = raw.strip_prefix(PREFIX).ok_or("签名数据格式不正确。")?;
    // 先按 base64 长度粗判体积再解码，避免为超大载荷先分配一遍内存
    if payload.len() / 4 * 3 > MAX_SIGN_BYTES {
        return Err("签名图像过大，请重新签名。".into());
    }
    let blob = B64.decode(payload).map_err(|_| "签名数据解析失败，请重新签名。")?;
    if !blob.starts_with(PNG_MAGIC) {
        return Err("签名数据不是有效的 PNG 图像。".into());
    }
    if blob.len() > MAX_SIGN_BYTES {
        return Err("签名图像过大，请重新签名。".into());
    }
    Ok(Some(blob))
}

/// 校验笔迹矢量 JSON；过大或非法则丢弃（不阻断业务，位图仍在）。
pub fn clean_meta(raw: &str) -> Option<String> {
    let raw = raw.trim();
    if raw.is_empty() || raw.len() > MAX_META_CHARS {
        return None;
    }
    serde_json::from_str::<serde_json::Value>(raw).ok()?;
    Some(raw.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    const PNG: &[u8] = &[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A, 0, 0, 0, 0x0D];

    fn data_url() -> String {
        format!("{PREFIX}{}", B64.encode(PNG))
    }

    #[test]
    fn required_rejects_empty() {
        for input in ["", "   "] {
            assert_eq!(decode(input, true).unwrap_err(), "请手写签名后再提交。");
        }
    }

    #[test]
    fn relaxed_accepts_empty() {
        // 留空就是无签名，不能凭空造一张图
        for input in ["", "   "] {
            assert_eq!(decode(input, false).unwrap(), None);
        }
    }

    /// 格式校验不受开关影响——签了就必须是合法 PNG。
    #[test]
    fn format_check_ignores_switch() {
        for required in [true, false] {
            assert_eq!(decode("data:image/jpeg;base64,AAAA", required).unwrap_err(),
                       "签名数据格式不正确。");
            assert_eq!(decode("data:image/png;base64,!!!", required).unwrap_err(),
                       "签名数据解析失败，请重新签名。");
            assert_eq!(decode("data:image/png;base64,QUJDRA==", required).unwrap_err(),
                       "签名数据不是有效的 PNG 图像。");
            assert_eq!(decode(&data_url(), required).unwrap().as_deref(), Some(PNG));
        }
    }

    #[test]
    fn oversized_signature_rejected() {
        let huge = B64.encode(vec![0u8; MAX_SIGN_BYTES + 1024]);
        assert_eq!(decode(&format!("{PREFIX}{huge}"), true).unwrap_err(),
                   "签名图像过大，请重新签名。");
    }

    #[test]
    fn meta_must_be_json() {
        assert_eq!(clean_meta(r#"{"strokes":[]}"#).as_deref(), Some(r#"{"strokes":[]}"#));
        assert_eq!(clean_meta(""), None);
        assert_eq!(clean_meta("{ 这不是 JSON"), None);
        // 过大直接丢弃，不阻断业务（位图仍在）
        assert_eq!(clean_meta(&"x".repeat(MAX_META_CHARS + 1)), None);
    }
}
