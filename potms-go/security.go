// 密码哈希 — bcrypt（兼容旧 werkzeug pbkdf2 哈希，登录透明升级）
package main

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"strconv"
	"strings"

	"golang.org/x/crypto/bcrypt"
	"golang.org/x/crypto/pbkdf2"
)

func hashPassword(password string) (string, error) {
	b, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	return string(b), err
}

// verifyPassword 返回 (是否匹配, 是否需升级为 bcrypt)
func verifyPassword(password, stored string) (bool, bool) {
	if stored == "" {
		return false, false
	}
	if strings.HasPrefix(stored, "$2") {
		return bcrypt.CompareHashAndPassword([]byte(stored), []byte(password)) == nil, false
	}
	// werkzeug 格式: pbkdf2:sha256:iterations$salt$hexhash
	if strings.HasPrefix(stored, "pbkdf2:sha256") {
		ok := verifyWerkzeugPBKDF2(password, stored)
		return ok, ok
	}
	return false, false
}

func verifyWerkzeugPBKDF2(password, stored string) bool {
	parts := strings.SplitN(stored, "$", 3)
	if len(parts) != 3 {
		return false
	}
	method, salt, hexHash := parts[0], parts[1], parts[2]
	iterations := 260000
	if mp := strings.SplitN(method, ":", 3); len(mp) == 3 {
		if n, err := strconv.Atoi(mp[2]); err == nil {
			iterations = n
		}
	}
	derived := pbkdf2.Key([]byte(password), []byte(salt), iterations, sha256.Size, sha256.New)
	return subtle.ConstantTimeCompare([]byte(hex.EncodeToString(derived)), []byte(hexHash)) == 1
}
