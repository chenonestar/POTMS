// 配置 — 与 Python 版 config.py 一一对应
package main

import (
	"crypto/rand"
	"encoding/hex"
	"os"
	"path/filepath"
	"strconv"
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
		if n, err := strconv.Atoi(v); err == nil {
			TZOffsetHours = n
		}
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
