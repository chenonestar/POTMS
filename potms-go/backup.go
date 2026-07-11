// 每日自动备份 + 保留 30 天（含进程内“今日已检查”标记）
package main

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const (
	retainDays   = 30
	backupPrefix = "data_"
	backupSuffix = ".db"
)

var (
	backupMu    sync.Mutex
	checkedDate string
)

type BackupResult struct {
	Created bool
	Path    string
	Pruned  int
	Date    string
}

func latestBackup() (string, string) {
	entries, err := os.ReadDir(BackupDir)
	if err != nil {
		return "", ""
	}
	var names []string
	for _, e := range entries {
		n := e.Name()
		if strings.HasPrefix(n, backupPrefix) && strings.HasSuffix(n, backupSuffix) {
			names = append(names, n)
		}
	}
	if len(names) == 0 {
		return "", ""
	}
	latest := names[0]
	for _, n := range names[1:] {
		if n > latest {
			latest = n
		}
	}
	return latest, strings.TrimSuffix(strings.TrimPrefix(latest, backupPrefix), backupSuffix)
}

func pruneOldBackups() int {
	cutoff := time.Now().AddDate(0, 0, -retainDays).Format("20060102")
	entries, err := os.ReadDir(BackupDir)
	if err != nil {
		return 0
	}
	removed := 0
	for _, e := range entries {
		n := e.Name()
		if strings.HasPrefix(n, backupPrefix) && strings.HasSuffix(n, backupSuffix) {
			ds := strings.TrimSuffix(strings.TrimPrefix(n, backupPrefix), backupSuffix)
			if len(ds) == 8 && ds < cutoff {
				if os.Remove(filepath.Join(BackupDir, n)) == nil {
					removed++
				}
			}
		}
	}
	return removed
}

func runDailyBackup(force bool) BackupResult {
	backupMu.Lock()
	defer backupMu.Unlock()
	today := time.Now().Format("20060102")
	if !force && checkedDate == today {
		return BackupResult{Date: today}
	}
	os.MkdirAll(BackupDir, 0o755)
	dest := filepath.Join(BackupDir, backupPrefix+today+backupSuffix)

	created := false
	if _, err := os.Stat(DatabasePath); err == nil {
		if _, err := os.Stat(dest); force || err != nil {
			if copyFile(DatabasePath, dest) == nil {
				created = true
			}
		}
	}
	pruned := pruneOldBackups()
	checkedDate = today
	res := BackupResult{Created: created, Pruned: pruned, Date: today}
	if created {
		res.Path = dest
	}
	return res
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}
