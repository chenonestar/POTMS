// 认证：登录（防爆破）/ 登出 / 账户设置
package main

import (
	"fmt"
	"net/http"
	"strings"
)

func handleLogin(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		username := strings.TrimSpace(r.PostFormValue("username"))
		password := r.PostFormValue("password")
		ip := clientIP(r)

		if remain := lockedRemaining(ip); remain > 0 {
			mins := remain/60 + 1
			flashMsg(w, r, fmt.Sprintf("登录失败次数过多，已临时锁定，请 %d 分钟后再试。", mins), "danger")
			render(w, r, "login.html", nil)
			return
		}
		if username == "" || password == "" {
			flashMsg(w, r, "请输入用户名和密码。", "danger")
			render(w, r, "login.html", nil)
			return
		}
		user := queryOne("SELECT * FROM users WHERE username = ?", username)
		ok, needsRehash := false, false
		if user != nil {
			ok, needsRehash = verifyPassword(password, rowStr(user, "password_hash"))
		}
		if ok {
			resetLoginFails(ip)
			if needsRehash {
				if h, err := hashPassword(password); err == nil {
					db.Exec("UPDATE users SET password_hash = ? WHERE id = ?", h, user["id"])
				}
			}
			s := getSession(r)
			s["logged_in"] = true
			s["username"] = username
			saveSession(w, r, s)
			flashMsg(w, r, "登录成功。", "success")
			redirect(w, r, "dashboard.index", nil)
			return
		}
		left := recordLoginFailure(r, ip, username)
		if left > 0 {
			flashMsg(w, r, fmt.Sprintf("用户名或密码错误（再失败 %d 次将锁定 %d 分钟）。", left, lockMinutes), "danger")
		} else {
			flashMsg(w, r, fmt.Sprintf("登录失败次数过多，已锁定 %d 分钟。", lockMinutes), "danger")
		}
	}
	render(w, r, "login.html", nil)
}

func handleLogout(w http.ResponseWriter, r *http.Request) {
	clearSession(w, r)
	flashMsg(w, r, "已退出登录。", "info")
	redirect(w, r, "auth.login", nil)
}

func handleAccount(w http.ResponseWriter, r *http.Request) {
	user := queryOne("SELECT * FROM users WHERE username = ?", sessionUser(r))
	if user == nil {
		clearSession(w, r)
		redirect(w, r, "auth.login", nil)
		return
	}
	if r.Method == http.MethodPost {
		currentPw := r.PostFormValue("current_password")
		newUsername := strings.TrimSpace(r.PostFormValue("new_username"))
		newPw := r.PostFormValue("new_password")
		confirmPw := r.PostFormValue("confirm_password")

		var errs []string
		if ok, _ := verifyPassword(currentPw, rowStr(user, "password_hash")); !ok {
			errs = append(errs, "当前密码不正确。")
		}
		changeUsername := newUsername != "" && newUsername != rowStr(user, "username")
		changePassword := newPw != ""
		if !changeUsername && !changePassword {
			errs = append(errs, "未检测到任何修改。")
		}
		if newUsername == "" {
			errs = append(errs, "用户名不能为空。")
		} else if changeUsername {
			if len([]rune(newUsername)) < 3 {
				errs = append(errs, "用户名至少 3 个字符。")
			} else if queryOne("SELECT id FROM users WHERE username = ? AND id != ?", newUsername, user["id"]) != nil {
				errs = append(errs, "该用户名已被占用。")
			}
		}
		if changePassword {
			if len(newPw) < 6 {
				errs = append(errs, "新密码至少 6 个字符。")
			} else if newPw != confirmPw {
				errs = append(errs, "两次输入的新密码不一致。")
			}
		}
		if len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "account.html", Row{"username": user["username"]})
			return
		}
		if changeUsername {
			db.Exec("UPDATE users SET username = ? WHERE id = ?", newUsername, user["id"])
		}
		if changePassword {
			h, _ := hashPassword(newPw)
			db.Exec("UPDATE users SET password_hash = ? WHERE id = ?", h, user["id"])
		}
		var parts []string
		if changeUsername {
			parts = append(parts, "用户名→"+newUsername)
		}
		if changePassword {
			parts = append(parts, "密码")
		}
		logAction(r, "update", "users", user["id"], "账户变更："+strings.Join(parts, "、"), nil, nil)

		if changePassword {
			clearSession(w, r)
			flashMsg(w, r, "密码已修改，请使用新密码重新登录。", "success")
			redirect(w, r, "auth.login", nil)
			return
		}
		s := getSession(r)
		s["username"] = newUsername
		saveSession(w, r, s)
		flashMsg(w, r, "账户信息已更新。", "success")
		redirect(w, r, "auth.account", nil)
		return
	}
	render(w, r, "account.html", Row{"username": user["username"]})
}
