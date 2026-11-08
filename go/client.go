package main

import (
	"bufio"
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	defaultURL  = "http://192.168.72.149:8090"
	successCode = "YMP-00000"
)

// ------------------------------------------------- 配置 (~/.ympctl.json, 与 Python 版互通)

type Config struct {
	URL       string `json:"url,omitempty"`
	User      string `json:"user,omitempty"`
	Token     string `json:"token,omitempty"`
	Password  string `json:"password,omitempty"`
	LoginTime string `json:"login_time,omitempty"`
}

func configPath() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".ympctl.json")
}

func loadConfig() Config {
	var c Config
	b, err := os.ReadFile(configPath())
	if err == nil {
		_ = json.Unmarshal(b, &c)
	}
	return c
}

func saveConfig(c Config) {
	b, _ := json.MarshalIndent(c, "", "  ")
	_ = os.WriteFile(configPath(), b, 0o600)
}

// ------------------------------------------------- HTTP 客户端

type Client struct {
	BaseURL string
	Token   string
	Timeout time.Duration
}

type ympResp struct {
	Code    string          `json:"code"`
	Message string          `json:"message"`
	Result  json.RawMessage `json:"result"`
}

func fail(format string, a ...any) {
	fmt.Fprintf(os.Stderr, "ympctl: 错误: %s\n", fmt.Sprintf(format, a...))
	os.Exit(1)
}

func truncate(b []byte, n int) string {
	s := string(b)
	if len(s) > n {
		return s[:n]
	}
	return s
}

// Request: params 为查询参数；body 非 nil 时作为 JSON/原始请求体；
// outFile 非空时把响应写入文件(先校验 JSON 错误体)。
func (c *Client) Request(method, path string, params url.Values, body []byte,
	headers map[string]string, outFile string) ([]byte, error) {
	u := strings.TrimRight(c.BaseURL, "/") + "/" + strings.TrimLeft(path, "/")
	if len(params) > 0 {
		u += "?" + params.Encode()
	}
	var rd io.Reader
	if body != nil {
		rd = bytes.NewReader(body)
	}
	req, err := http.NewRequest(method, u, rd)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	if c.Token != "" {
		req.Header.Set("Access-Token", c.Token)
		req.Header.Set("Authorization", c.Token)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json; charset=UTF-8")
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := (&http.Client{Timeout: c.Timeout}).Do(req)
	if err != nil {
		return nil, fmt.Errorf("连接/传输失败(%s %s): %v", method, path, err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)

	if resp.StatusCode == http.StatusUnauthorized {
		return nil, fmt.Errorf("认证失败(401)：Token 缺失或已过期，请先执行 ympctl login")
	}
	if outFile != "" {
		if len(bytes.TrimSpace(data)) > 0 && bytes.TrimSpace(data)[0] == '{' {
			var r ympResp
			_ = json.Unmarshal(bytes.TrimSpace(data), &r)
			if r.Code != "" && r.Code != successCode {
				return nil, fmt.Errorf("下载失败，YMP 错误 %s: %s", r.Code, r.Message)
			}
		}
		if err := os.WriteFile(outFile, data, 0o644); err != nil {
			return nil, err
		}
		return data, nil
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, truncate(data, 200))
	}
	if len(bytes.TrimSpace(data)) == 0 {
		return nil, nil
	}
	var r ympResp
	if err := json.Unmarshal(data, &r); err != nil {
		return nil, fmt.Errorf("响应不是 JSON(可能接口路径错误): %s", truncate(data, 200))
	}
	if r.Code != successCode {
		return nil, fmt.Errorf("YMP 错误 %s: %s", r.Code, r.Message)
	}
	return r.Result, nil
}

// decodeAny: json.Number 保留字面量(如 100.0)
func decodeAny(b []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return v, nil
}

func (c *Client) Get(path string, params url.Values) any {
	res, err := c.Request("GET", path, params, nil, nil, "")
	if err != nil {
		fail("%v", err)
	}
	return mustAny(res)
}

func (c *Client) PostRaw(path string, body []byte) any {
	res, err := c.Request("POST", path, nil, body, nil, "")
	if err != nil {
		fail("%v", err)
	}
	if res == nil {
		return nil
	}
	return mustAny(res)
}

func (c *Client) PostJSON(path string, payload any) any {
	b, _ := json.Marshal(payload)
	return c.PostRaw(path, b)
}

func (c *Client) GetOut(path string, params url.Values, headers map[string]string, outFile string) {
	if _, err := c.Request("GET", path, params, nil, headers, outFile); err != nil {
		fail("%v", err)
	}
}

func (c *Client) PostRawOut(path string, body []byte, headers map[string]string, outFile string) {
	if _, err := c.Request("POST", path, nil, body, headers, outFile); err != nil {
		fail("%v", err)
	}
}

func mustAny(b []byte) any {
	if len(bytes.TrimSpace(b)) == 0 {
		return nil
	}
	v, err := decodeAny(b)
	if err != nil {
		fail("解析响应失败: %v", err)
	}
	return v
}

// ------------------------------------------------- 登录/加密

func sha256Hex(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

var aesKey = []byte("1234567890123456") // key 与 iv 相同, 与 YMP 前端一致

// EncryptPassword: AES-128-CBC + ZeroPadding(crypto-js 对齐也补整块) + Base64
func EncryptPassword(text string) string {
	if text == "" {
		return ""
	}
	data := []byte(text)
	pad := 16 - len(data)%16
	for i := 0; i < pad; i++ {
		data = append(data, 0)
	}
	block, err := aes.NewCipher(aesKey)
	if err != nil {
		fail("AES 初始化失败: %v", err)
	}
	out := make([]byte, len(data))
	cipher.NewCBCEncrypter(block, aesKey).CryptBlocks(out, data)
	return base64.StdEncoding.EncodeToString(out)
}

// newClient: urlFlag > YMP_URL > 配置 > 默认
func newClient(urlFlag string, timeoutFlag int, noToken bool) *Client {
	cfg := loadConfig()
	base := urlFlag
	if base == "" {
		base = os.Getenv("YMP_URL")
	}
	if base == "" {
		base = cfg.URL
	}
	if base == "" {
		base = defaultURL
	}
	timeout := 60 * time.Second
	if timeoutFlag > 0 {
		timeout = time.Duration(timeoutFlag) * time.Second
	}
	token := os.Getenv("YMP_TOKEN")
	if token == "" {
		token = cfg.Token
	}
	if noToken {
		token = ""
	}
	return &Client{BaseURL: strings.TrimRight(base, "/"), Token: token, Timeout: timeout}
}

func doLogin(c *Client, user, password string, savePW bool) {
	if user == "" || password == "" {
		fail("缺少用户名或密码(--user / --password / --password-stdin / 环境变量)")
	}
	res := c.PostJSON("yashan/user/login", map[string]string{
		"userName": user, "password": sha256Hex(password)})
	m, _ := res.(map[string]any)
	tok, _ := m["token"].(string)
	if tok == "" {
		fail("登录成功但未返回 token: %s", fmtCell(res))
	}
	cfg := loadConfig()
	cfg.URL, cfg.User, cfg.Token = c.BaseURL, user, tok
	cfg.LoginTime = time.Now().Format("2006-01-02 15:04:05")
	if savePW {
		cfg.Password = password
	} else {
		cfg.Password = ""
	}
	saveConfig(cfg)
}

func ensureToken(c *Client) {
	if c.Token != "" {
		return
	}
	cfg := loadConfig()
	user, pw := cfg.User, cfg.Password
	if user == "" {
		user = os.Getenv("YMP_USER")
	}
	if pw == "" {
		pw = os.Getenv("YMP_PASSWORD")
	}
	if user != "" && pw != "" {
		doLogin(c, user, pw, true)
		return
	}
	fail("尚未登录或 Token 失效，请先执行: ympctl login")
}

// ------------------------------------------------- ID 解析

func getMap(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func getList(v any) []any {
	l, _ := v.([]any)
	return l
}

func mapGet(m map[string]any, key string) any {
	if m == nil {
		return nil
	}
	return m[key]
}

// resolveMigrationID: --migration-id 优先, 否则取 getTaskBaseInfo 的 migrationTask.id
func resolveMigrationID(c *Client, midFlag int, taskID int) int {
	if midFlag > 0 {
		return midFlag
	}
	base := getMap(c.Get(fmt.Sprintf("yashan/task/getTaskBaseInfo/%d", taskID), nil))
	mt := getMap(base["migrationTask"])
	if id := numInt(mt["id"]); id > 0 {
		return int(id)
	}
	fail("任务 %d 尚无迁移子任务(migrationTask)，无法定位 migrationTaskId；"+
		"请先在向导中保存迁移配置，或用 -m/--migration-id 显式指定", taskID)
	return 0
}

// resolveCheckID: 主任务ID或checkTaskId → (checkTaskId, checkTask信息)
func resolveCheckID(c *Client, cid int) (int, map[string]any) {
	base := getMap(c.Get(fmt.Sprintf("yashan/task/getTaskBaseInfo/%d", cid), nil))
	ct := getMap(base["checkTask"])
	if id := numInt(ct["id"]); id > 0 {
		return int(id), ct
	}
	info := getMap(c.Get(fmt.Sprintf("yashan/check/status/info/%d", cid), nil))
	if id := numInt(info["id"]); id > 0 {
		recs := getList(getMap(c.Get("yashan/task/getTaskList",
			paramsOf("pageNum", "1", "pageSize", "100")))["records"])
		for _, r := range recs {
			rm := getMap(r)
			tid := int(numInt(rm["id"]))
			b := getMap(c.Get(fmt.Sprintf("yashan/task/getTaskBaseInfo/%d", tid), nil))
			t := getMap(b["checkTask"])
			if numInt(t["id"]) == id {
				merged := map[string]any{}
				for k, v := range t {
					merged[k] = v
				}
				for k, v := range info {
					merged[k] = v
				}
				return int(id), merged
			}
		}
		return int(id), info
	}
	fail("任务 %d 不是校验任务(无 checkTask 子任务)，也无法作为 checkTaskId 定位；"+
		"请用 check list 查看可用的校验任务", cid)
	return 0, nil
}

// paramsOf: k1,v1,k2,v2... 构造 url.Values
func paramsOf(kv ...string) url.Values {
	p := url.Values{}
	for i := 0; i+1 < len(kv); i += 2 {
		p.Add(kv[i], kv[i+1])
	}
	return p
}

// parseDataArg: JSON 字符串 / @file / -(stdin) → 原始字节
func parseDataArg(s string) []byte {
	if s == "" {
		return nil
	}
	if s == "-" {
		b, _ := io.ReadAll(os.Stdin)
		return b
	}
	if strings.HasPrefix(s, "@") {
		b, err := os.ReadFile(s[1:])
		if err != nil {
			fail("读取 --data 文件失败: %v", err)
		}
		return b
	}
	return []byte(s)
}

// buildMultipartField: name/file 两段 multipart 请求体
func buildMultipartField(name, filename string, content []byte, fieldName string) ([]byte, string) {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	_ = w.WriteField(name, name)
	fw, _ := w.CreateFormFile(fieldName, filename)
	_, _ = fw.Write(content)
	_ = w.Close()
	return buf.Bytes(), w.FormDataContentType()
}

// writeMigrateImport: 构造 config/import 的 multipart 体
func writeMigrateImport(migrationID int, file string) ([]byte, string) {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	_ = w.WriteField("migrationId", fmt.Sprintf("%d", migrationID))
	fw, _ := w.CreateFormFile("file", filepath.Base(file))
	content, err := os.ReadFile(file)
	if err != nil {
		fail("读取文件失败: %v", err)
	}
	_, _ = fw.Write(content)
	_ = w.Close()
	return buf.Bytes(), w.FormDataContentType()
}

func readLine(prompt string) string {
	fmt.Print(prompt)
	rd := bufio.NewReader(os.Stdin)
	s, _ := rd.ReadString('\n')
	return strings.TrimSpace(s)
}
