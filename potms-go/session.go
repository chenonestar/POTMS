// 会话（HMAC 签名 Cookie）+ Flash 消息 + CSRF + 登录防爆破
package main

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"
)

const sessionCookie = "potms_session"

type Session map[string]interface{}

// ctx 每请求会话缓存（避免重复解析/丢失同请求内修改）
var (
	sessMu    sync.Mutex
	sessStore = map[*http.Request]Session{}
)

func sign(payload []byte) string {
	mac := hmac.New(sha256.New, SecretKey)
	mac.Write(payload)
	return base64.RawURLEncoding.EncodeToString(payload) + "." +
		base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func verify(token string) []byte {
	parts := strings.SplitN(token, ".", 2)
	if len(parts) != 2 {
		return nil
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return nil
	}
	sig, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return nil
	}
	mac := hmac.New(sha256.New, SecretKey)
	mac.Write(payload)
	if !hmac.Equal(sig, mac.Sum(nil)) {
		return nil
	}
	return payload
}

// getSession 读取（并缓存）当前请求会话；过期或无效返回空会话
func getSession(r *http.Request) Session {
	sessMu.Lock()
	if s, ok := sessStore[r]; ok {
		sessMu.Unlock()
		return s
	}
	sessMu.Unlock()
	s := Session{}
	if c, err := r.Cookie(sessionCookie); err == nil {
		if payload := verify(c.Value); payload != nil {
			var m map[string]interface{}
			if json.Unmarshal(payload, &m) == nil {
				if exp, ok := m["_exp"].(float64); ok && int64(exp) > time.Now().Unix() {
					s = m
				}
			}
		}
	}
	sessMu.Lock()
	sessStore[r] = s
	sessMu.Unlock()
	return s
}

// saveSession 写回会话 Cookie（滑动过期，等价 Flask permanent session 刷新）
func saveSession(w http.ResponseWriter, r *http.Request, s Session) {
	s["_exp"] = time.Now().Unix() + int64(SessionLifetimeSec)
	payload, _ := json.Marshal(s)
	http.SetCookie(w, &http.Cookie{
		Name: sessionCookie, Value: sign(payload), Path: "/",
		HttpOnly: true, SameSite: http.SameSiteLaxMode,
		MaxAge: SessionLifetimeSec,
	})
	sessMu.Lock()
	sessStore[r] = s
	sessMu.Unlock()
}

func clearSession(w http.ResponseWriter, r *http.Request) {
	http.SetCookie(w, &http.Cookie{Name: sessionCookie, Value: "", Path: "/", MaxAge: -1})
	sessMu.Lock()
	sessStore[r] = Session{}
	sessMu.Unlock()
}

func releaseSession(r *http.Request) {
	sessMu.Lock()
	delete(sessStore, r)
	sessMu.Unlock()
}

func isLoggedIn(r *http.Request) bool {
	v, _ := getSession(r)["logged_in"].(bool)
	return v
}

func sessionUser(r *http.Request) string {
	if u, ok := getSession(r)["username"].(string); ok {
		return u
	}
	return "admin"
}

// ---------------------------------------------------------------------------
// Flash 消息（存会话，读取即清除 — 等价 Flask flash）
// ---------------------------------------------------------------------------
func flashMsg(w http.ResponseWriter, r *http.Request, message, category string) {
	s := getSession(r)
	var flashes []interface{}
	if f, ok := s["_flashes"].([]interface{}); ok {
		flashes = f
	}
	flashes = append(flashes, []interface{}{category, message})
	s["_flashes"] = flashes
	saveSession(w, r, s)
}

func popFlashes(w http.ResponseWriter, r *http.Request) [][2]string {
	s := getSession(r)
	f, ok := s["_flashes"].([]interface{})
	if !ok || len(f) == 0 {
		return nil
	}
	delete(s, "_flashes")
	saveSession(w, r, s)
	var out [][2]string
	for _, item := range f {
		if pair, ok := item.([]interface{}); ok && len(pair) == 2 {
			out = append(out, [2]string{fmt.Sprintf("%v", pair[0]), fmt.Sprintf("%v", pair[1])})
		}
	}
	return out
}

// ---------------------------------------------------------------------------
// CSRF（会话随机令牌 + 常量时间比对；表单域 / X-CSRFToken / 查询串）
// ---------------------------------------------------------------------------
func csrfToken(w http.ResponseWriter, r *http.Request) string {
	s := getSession(r)
	if t, ok := s["_csrf_token"].(string); ok && t != "" {
		return t
	}
	buf := make([]byte, 32)
	rand.Read(buf)
	t := hex.EncodeToString(buf)
	s["_csrf_token"] = t
	saveSession(w, r, s)
	return t
}

func csrfOK(r *http.Request) bool {
	switch r.Method {
	case "GET", "HEAD", "OPTIONS", "TRACE":
		return true
	}
	expected, _ := getSession(r)["_csrf_token"].(string)
	sent := r.PostFormValue("csrf_token")
	if sent == "" {
		sent = r.Header.Get("X-CSRFToken")
	}
	if sent == "" {
		sent = r.URL.Query().Get("csrf_token")
	}
	return expected != "" && sent != "" &&
		subtle.ConstantTimeCompare([]byte(expected), []byte(sent)) == 1
}

// ---------------------------------------------------------------------------
// 登录防爆破：按来源 IP 计失败，连续 5 次锁定 10 分钟
// ---------------------------------------------------------------------------
const (
	maxLoginFails = 5
	lockMinutes   = 10
)

type failState struct {
	Count     int
	LockUntil time.Time
}

var (
	failMu     sync.Mutex
	loginFails = map[string]*failState{}
)

func lockedRemaining(ip string) int {
	failMu.Lock()
	defer failMu.Unlock()
	st := loginFails[ip]
	if st == nil {
		return 0
	}
	if !st.LockUntil.IsZero() {
		if remain := time.Until(st.LockUntil); remain > 0 {
			return int(remain.Seconds())
		}
		st.Count = 0
		st.LockUntil = time.Time{}
	}
	return 0
}

// recordLoginFailure 返回剩余可尝试次数（0 表示本次触发锁定）
func recordLoginFailure(r *http.Request, ip, username string) int {
	failMu.Lock()
	st := loginFails[ip]
	if st == nil {
		st = &failState{}
		loginFails[ip] = st
	}
	st.Count++
	locked := st.Count >= maxLoginFails
	if locked {
		st.LockUntil = time.Now().Add(lockMinutes * time.Minute)
	}
	count := st.Count
	failMu.Unlock()
	if locked {
		logAction(r, "lock", "users", nil,
			fmt.Sprintf("登录连续失败 %d 次，锁定 %d 分钟（尝试用户名: %s，IP: %s）", count, lockMinutes, username, ip),
			nil, nil)
	}
	return maxLoginFails - count
}

func resetLoginFails(ip string) {
	failMu.Lock()
	delete(loginFails, ip)
	failMu.Unlock()
}
