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
			// 单据上的经办人取这个；没填姓名时回退到账号，保证字段永不为空
			if fn := strings.TrimSpace(rowStr(user, "full_name")); fn != "" {
				s["full_name"] = fn
			} else {
				s["full_name"] = username
			}
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
		newFullName := strings.TrimSpace(r.PostFormValue("new_full_name"))
		newPw := r.PostFormValue("new_password")
		confirmPw := r.PostFormValue("confirm_password")

		var errs []string
		if ok, _ := verifyPassword(currentPw, rowStr(user, "password_hash")); !ok {
			errs = append(errs, "当前密码不正确。")
		}
		changeUsername := newUsername != "" && newUsername != rowStr(user, "username")
		changePassword := newPw != ""
		changeFullName := newFullName != rowStr(user, "full_name")
		if !changeUsername && !changePassword && !changeFullName {
			errs = append(errs, "未检测到任何修改。")
		}
		if len([]rune(newFullName)) > 30 {
			errs = append(errs, "姓名过长（最多 30 个字符）。")
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
			render(w, r, "account.html", accountView(user))
			return
		}
		if changeUsername {
			db.Exec("UPDATE users SET username = ? WHERE id = ?", newUsername, user["id"])
		}
		if changePassword {
			h, _ := hashPassword(newPw)
			db.Exec("UPDATE users SET password_hash = ? WHERE id = ?", h, user["id"])
		}
		if changeFullName {
			var v interface{}
			if newFullName != "" {
				v = newFullName
			}
			db.Exec("UPDATE users SET full_name = ? WHERE id = ?", v, user["id"])
		}
		var parts []string
		if changeUsername {
			parts = append(parts, "用户名→"+newUsername)
		}
		if changeFullName {
			shown := newFullName
			if shown == "" {
				shown = "（清空）"
			}
			parts = append(parts, "姓名→"+shown)
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
		if newFullName != "" {
			s["full_name"] = newFullName
		} else {
			s["full_name"] = newUsername
		}
		saveSession(w, r, s)
		flashMsg(w, r, "账户信息已更新。", "success")
		redirect(w, r, "auth.account", nil)
		return
	}
	render(w, r, "account.html", accountView(user))
}

// ---------------------------------------------------------------------------
// 历史经办人回填
//
// 升级那一刻系统还不知道真实姓名——得先去账户设置填。所以「加列」和「改历史
// 数据」不能是同一步，回填只能等姓名填好之后由用户显式触发。
//
// 刻意做成按钮而不是升级时静默 UPDATE：批量改历史数据不可逆，得让人看清影响
// 条数再点。执行前自动备一次库，整件事也记进操作日志。
// ---------------------------------------------------------------------------

// 业务表的经办人字段。operation_logs 不在其列——那是审计痕迹，记的是账号。
var operatorColumns = [][2]string{
	{"personnel_info", "operator"},
	{"personnel_filing", "operator"},
	{"certificates", "operator"},
	{"travel_details", "operator"},
	{"decontrol_filing", "operator"},
	{"cert_issuance", "operator"},
	{"cert_issuance", "issuer"},
	{"cert_issuance", "return_operator"},
}

// legacyOperatorCount 统计业务表里还有多少条记录把登录账号当经办人。
func legacyOperatorCount(username string) int64 {
	var total int64
	for _, tc := range operatorColumns {
		var n int64
		// 老库可能还没有 cert_issuance 表，查不到就跳过
		if err := db.QueryRow(
			"SELECT COUNT(*) FROM "+tc[0]+" WHERE "+tc[1]+" = ?", username).Scan(&n); err != nil {
			continue
		}
		total += n
	}
	return total
}

func accountView(user Row) Row {
	username := rowStr(user, "username")
	return Row{
		"username":  username,
		"full_name": rowStr(user, "full_name"),
		"legacy":    Row{"username": username, "total": legacyOperatorCount(username)},
	}
}

// handleBackfillOperator 把业务表里等于登录账号的经办人，批量改成真实姓名。
func handleBackfillOperator(w http.ResponseWriter, r *http.Request) {
	user := queryOne("SELECT * FROM users WHERE username = ?", sessionUser(r))
	if user == nil {
		clearSession(w, r)
		redirect(w, r, "auth.login", nil)
		return
	}
	username := rowStr(user, "username")
	fullName := strings.TrimSpace(rowStr(user, "full_name"))
	if fullName == "" {
		flashMsg(w, r, "请先填写并保存姓名，再回填历史记录。", "warning")
		redirect(w, r, "auth.account", nil)
		return
	}
	if fullName == username {
		flashMsg(w, r, "姓名与登录账号相同，无需回填。", "info")
		redirect(w, r, "auth.account", nil)
		return
	}

	// 不可逆的批量写入，先留一份退路。force：当天已备过也要再备，因为马上要改数据。
	// runDailyBackup 吞掉了复制错误，所以按产物判断成败，而不是看它返回没返回。
	if res := runDailyBackup(true); !res.Created {
		flashMsg(w, r, "自动备份失败，已中止回填。请手动备份 data.db 后重试。", "danger")
		redirect(w, r, "auth.account", nil)
		return
	}

	var changed int64
	for _, tc := range operatorColumns {
		res, err := db.Exec("UPDATE "+tc[0]+" SET "+tc[1]+" = ? WHERE "+tc[1]+" = ?", fullName, username)
		if err != nil {
			continue
		}
		n, _ := res.RowsAffected()
		changed += n
	}

	logAction(r, "update", "users", user["id"],
		fmt.Sprintf("历史经办人回填：%s → %s，共 %d 条", username, fullName, changed), nil, nil)
	flashMsg(w, r, fmt.Sprintf(
		"已把 %d 条历史记录的经办人由「%s」更新为「%s」。操作日志保持原样（审计需要登录账号）。",
		changed, username, fullName), "success")
	redirect(w, r, "auth.account", nil)
}
