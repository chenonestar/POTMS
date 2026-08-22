// 配置 — 与 Python 版 config.py 一一对应
package main

import (
	"crypto/rand"
	"encoding/hex"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

var (
	BaseDir      string
	DatabasePath string
	UploadDir    string
	ExportDir    string
	BackupDir    string
	SecretKey    []byte

	PageSize     = 12 // 业务列表每页（前端窗口化下作为兜底）
	PageSizeLogs = 10 // 操作日志每页

	SessionLifetimeSec = 3600     // 会话 1 小时超时
	MaxContentLength   = 10 << 20 // 上传 10MB
	CertWarnDays       = 30       // 证照到期预警天数
	TZOffsetHours      = 8        // 显示时区偏移（store UTC / display local）

	// 证件领用 / 归还是否强制手写签名（POTMS_REQUIRE_SIGNATURE，默认强制）。
	//
	// 默认强制：签名就是「本人确实领了/还了」的凭证，一旦允许留空，这条记录就只剩
	// 经办人的一面之词。放宽必须是明确的选择，不能是默认值。
	//
	// 单位尚未配备手写板、或存在代领代还与历史回填记录时，设 POTMS_REQUIRE_SIGNATURE=0
	// 暂时放宽。放宽后签名板仍然显示（能签就签），只是留空也能提交。
	RequireSignature = true
)

func initConfig() {
	exe, err := os.Executable()
	if err != nil {
		exe = "."
	}
	BaseDir = filepath.Dir(exe)
	// 开发模式：go run 的临时目录不适合放数据，回退到工作目录
	if isTempPath(BaseDir) || os.Getenv("POTMS_DEV") == "1" {
		BaseDir, _ = os.Getwd()
	}
	if v := os.Getenv("POTMS_BASE"); v != "" {
		BaseDir = v
	}
	DatabasePath = filepath.Join(BaseDir, "data.db")
	UploadDir = filepath.Join(BaseDir, "uploads")
	ExportDir = filepath.Join(BaseDir, "exports")
	BackupDir = filepath.Join(BaseDir, "backup")
	for _, d := range []string{UploadDir, ExportDir, BackupDir} {
		os.MkdirAll(d, 0o755)
	}
	if v := os.Getenv("POTMS_TZ_OFFSET"); v != "" {
		if n, err := strconv.Atoi(strings.TrimSpace(v)); err == nil {
			TZOffsetHours = n
		}
	}
	switch strings.ToLower(strings.TrimSpace(os.Getenv("POTMS_REQUIRE_SIGNATURE"))) {
	case "0", "false", "no", "off":
		RequireSignature = false
	default:
		RequireSignature = true
	}
	SecretKey = loadOrCreateSecret()
}

func isTempPath(p string) bool {
	tmp := os.TempDir()
	rel, err := filepath.Rel(tmp, p)
	return err == nil && !filepath.IsAbs(rel) && rel != ".." && !hasDotDotPrefix(rel)
}

func hasDotDotPrefix(rel string) bool {
	return len(rel) >= 2 && rel[:2] == ".."
}

// loadOrCreateSecret 持久化会话密钥（与 Python 版 .secret_key 行为一致）
func loadOrCreateSecret() []byte {
	if env := os.Getenv("SECRET_KEY"); env != "" {
		return []byte(env)
	}
	keyFile := filepath.Join(BaseDir, ".secret_key")
	if b, err := os.ReadFile(keyFile); err == nil && len(b) >= 32 {
		return b
	}
	buf := make([]byte, 32)
	rand.Read(buf)
	key := []byte(hex.EncodeToString(buf))
	os.WriteFile(keyFile, key, 0o600)
	return key
}
