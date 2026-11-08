package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"strings"
)

func cmdAccount(args []string) int {
	if len(args) == 0 {
		printMainHelp()
		return 0
	}
	switch args[0] {
	case "login":
		return accountLogin(args[1:])
	case "logout":
		return accountLogout(args[1:])
	case "status":
		return accountStatus(args[1:])
	case "passwd":
		return accountPasswd(args[1:])
	case "encrypt":
		return accountEncrypt(args[1:])
	}
	fmt.Fprintf(os.Stderr, "未知子命令 %q\n", args[0])
	return 2
}

func accountLogin(args []string) int {
	fs := flag.NewFlagSet("login", flag.ExitOnError)
	var user, password, urlF string
	var pwStdin, savePW bool
	var timeout int
	fs.StringVar(&user, "user", os.Getenv("YMP_USER"), "用户名")
	fs.StringVar(&password, "password", "", "密码(建议 --password-stdin)")
	fs.BoolVar(&pwStdin, "password-stdin", false, "从 stdin 读取密码")
	fs.BoolVar(&savePW, "save-password", false, "明文保存密码(自动化慎用)")
	fs.StringVar(&urlF, "url", "", "YMP 地址")
	fs.IntVar(&timeout, "timeout", 0, "HTTP 超时秒数")
	fs.Parse(reorderArgs(args))

	if pwStdin {
		s, _ := bufio.NewReader(os.Stdin).ReadString('\n')
		password = strings.TrimRight(s, "\r\n")
	}
	c := newClient(urlF, timeout, false)
	if password == "" {
		password = os.Getenv("YMP_PASSWORD")
	}
	if password == "" {
		password = readLine("YMP 密码: ")
	}
	doLogin(c, user, password, savePW)
	cfg := loadConfig()
	fmt.Printf("登录成功: %s (user=%s)\n", c.BaseURL, cfg.User)
	fmt.Printf("Token 已保存到 %s\n", configPath())
	if savePW {
		fmt.Println("警告: 密码已明文保存在配置文件中，仅供自动化使用")
	}
	return 0
}

func accountLogout(args []string) int {
	fs := flag.NewFlagSet("logout", flag.ExitOnError)
	var urlF string
	var timeout int
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.Parse(reorderArgs(args))
	c := newClient(urlF, timeout, false)
	if c.Token != "" {
		c.PostRaw("yashan/user/logout", nil)
	}
	cfg := loadConfig()
	cfg.Token = ""
	saveConfig(cfg)
	fmt.Println("已登出并清除本地 Token")
	return 0
}

func accountStatus(args []string) int {
	fs := flag.NewFlagSet("status", flag.ExitOnError)
	var jsonMode bool
	var urlF string
	var timeout int
	fs.BoolVar(&jsonMode, "json", false, "输出原始 JSON")
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.Parse(reorderArgs(args))

	c := newClient(urlF, timeout, false)
	info := getMap(c.Get("yashan/platform/getInfo", nil))
	if jsonMode {
		emit(info, true)
		return 0
	}
	for _, kv := range [][2]string{
		{"YMP 地址", c.BaseURL},
		{"YMP 版本", fmtCell(info["ympVersion"])},
		{"YashanDB 版本", fmtCell(info["yashanDBVersion"])},
		{"yasldr 版本", fmtCell(info["yasldrVersion"])},
		{"JDBC 版本", fmtCell(info["jdbcVersion"])},
		{"OCI 版本", fmtCell(info["ociVersion"])},
	} {
		if kv[1] != "-" && kv[1] != "" {
			fmt.Printf("%s %s\n", pad(kv[0]+":", 18), kv[1])
		}
	}
	cfg := loadConfig()
	if cfg.User != "" {
		u := getMap(c.Get("yashan/user/info", paramsOf("userName", cfg.User)))
		fmt.Printf("%s %s (状态=%s)\n", pad("当前用户:", 18),
			fmtCell(u["userName"]), fmtCell(u["status"]))
	}
	return 0
}

func accountPasswd(args []string) int {
	fs := flag.NewFlagSet("passwd", flag.ExitOnError)
	var user, old, newPW, urlF string
	var timeout int
	fs.StringVar(&user, "user", "", "用户名(默认当前登录用户)")
	fs.StringVar(&old, "old", "", "旧密码")
	fs.StringVar(&newPW, "new", "", "新密码")
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.Parse(reorderArgs(args))

	c := newClient(urlF, timeout, false)
	ensureToken(c)
	cfg := loadConfig()
	if user == "" {
		user = cfg.User
	}
	if old == "" {
		old = readLine("当前密码: ")
	}
	if newPW == "" {
		newPW = readLine("新密码: ")
	}
	c.PostJSON("yashan/user/password", map[string]string{
		"userName":    user,
		"oldPassword": sha256Hex(old),
		"newPassword": sha256Hex(newPW),
	})
	doLogin(c, user, newPW, cfg.Password != "")
	fmt.Println("密码修改成功，已重新登录")
	return 0
}

func accountEncrypt(args []string) int {
	// encrypt <text> 或 echo xx | ympctl encrypt -
	text := ""
	if len(args) >= 1 {
		text = args[0]
	}
	if text == "" {
		fail("用法: ympctl encrypt <text>   或   echo <text> | ympctl encrypt -")
	}
	if text == "-" {
		s, _ := bufio.NewReader(os.Stdin).ReadString('\n')
		text = strings.TrimRight(s, "\r\n")
	}
	fmt.Println(EncryptPassword(text))
	return 0
}
