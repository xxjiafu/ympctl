package main

import (
	"encoding/json"
	"reflect"
	"testing"
)

// 加密结果与 Python 版逐字节对照(实测值)
func TestEncryptPasswordParity(t *testing.T) {
	cases := map[string]string{
		"x":        "iMCXJz8toWzYIoMHP61zBg==",
		"Cod-2022": "5FNiDVLTY0HxAz5y5f3j1A==",
		"":         "",
	}
	for in, want := range cases {
		if got := EncryptPassword(in); got != want {
			t.Errorf("EncryptPassword(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestEncryptPasswordDeterministic(t *testing.T) {
	a := EncryptPassword("ympctl-regression-测试")
	b := EncryptPassword("ympctl-regression-测试")
	if a != b || a == "" {
		t.Errorf("同输入应产出相同密文, got %q vs %q", a, b)
	}
	if len(a)%4 != 0 { // base64
		t.Errorf("密文应为合法 Base64 长度: %q", a)
	}
}

func TestSHA256Hex(t *testing.T) {
	// NIST FIPS-180 公认向量
	cases := map[string]string{
		"":    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
		"abc": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
	}
	for in, want := range cases {
		if got := sha256Hex(in); got != want {
			t.Errorf("sha256Hex(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestFmtMB(t *testing.T) {
	cases := []struct {
		in   any
		want string
	}{
		{json.Number("64"), "0.06MB(原始64KB)"},
		{json.Number("2048"), "2.00MB"},
		{json.Number("1048576"), "1024.00MB"},
		{nil, "-"},
		{"abc", "abc"},
	}
	for _, c := range cases {
		if got := fmtMB(c.in); got != c.want {
			t.Errorf("fmtMB(%v) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestParseRowData(t *testing.T) {
	cases := []struct {
		in   any
		want string
	}{
		{`["ccc"]`, "ccc"},
		{`["3026:4:0:148:2"]`, "3026:4:0:148:2"},
		{nil, "-"},
		{"plain", "plain"},
	}
	for _, c := range cases {
		if got := parseRowData(c.in); got != c.want {
			t.Errorf("parseRowData(%v) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestReorderArgs(t *testing.T) {
	cases := []struct {
		in, want []string
	}{
		{[]string{"show", "2", "--brief"},
			[]string{"--brief", "show", "2"}},
		{[]string{"start", "1", "--json"},
			[]string{"--json", "start", "1"}},
		{[]string{"log", "1", "--lines", "3", "--json"},
			[]string{"--lines", "3", "--json", "log", "1"}},
		{[]string{"api", "GET", "p", "--data", "-", "--raw"},
			[]string{"--data", "-", "--raw", "api", "GET", "p"}},
		{[]string{"export-config", "1", "-o", "a.json", "--modules", "config,objects"},
			[]string{"-o", "a.json", "--modules", "config,objects", "export-config", "1"}},
	}
	for _, c := range cases {
		got := reorderArgs(c.in)
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("reorderArgs(%v) = %v, want %v", c.in, got, c.want)
		}
	}
}

func TestNumInt(t *testing.T) {
	cases := []struct {
		in   any
		want int64
	}{
		{json.Number("42"), 42},
		{json.Number("1804"), 1804},
		{float64(3.9), 3},
		{"12", 12},
		{nil, 0},
	}
	for _, c := range cases {
		if got := numInt(c.in); got != c.want {
			t.Errorf("numInt(%v) = %d, want %d", c.in, got, c.want)
		}
	}
}

func TestLabels(t *testing.T) {
	if got := label(taskStatus, json.Number("9")); got != "迁移完成" {
		t.Errorf("taskStatus(9) = %q", got)
	}
	if got := label(diffType, json.Number("0")); got != "冗余" {
		t.Errorf("diffType(0) = %q", got)
	}
	if got := label(tableDiffType, json.Number("1")); got != "数据不一致" {
		t.Errorf("tableDiffType(1) = %q", got)
	}
	if got := label(tableCheckResult, json.Number("7")); got != "不一致" {
		t.Errorf("tableCheckResult(7) = %q", got)
	}
}

func TestOrDash(t *testing.T) {
	if got := orDash([]any{}); got != "-" {
		t.Errorf("orDash(empty) = %q", got)
	}
	if got := orDash(nil); got != "-" {
		t.Errorf("orDash(nil) = %q", got)
	}
	if got := orDash([]any{"A", "B"}); got != "A,B" {
		t.Errorf("orDash([A B]) = %q", got)
	}
}
