# Git Push 报错：HTTP/2 stream 未正常关闭

## 现象
- 推送时出现类似报错：
  - `HTTP/2 stream 1 was not closed cleanly before end of the underlying stream`
  - `fatal: unable to access '<repo-url>'`

## 常见原因
- 网络链路抖动或中间代理对 HTTP/2 支持不稳定。
- 本机代理配置可达性异常（例如代理端口不可用）。

## 快速修复（推荐）
仅在当前仓库切换到 HTTP/1.1：

```bash
git config http.version HTTP/1.1
git push origin main
```

检查是否生效：

```bash
git config --show-origin --get http.version
```

## 进一步排查
查看远端：

```bash
git remote -v
```

查看代理变量：

```bash
env | rg '^(HTTP|HTTPS|ALL)_PROXY='
```

## 回滚设置（可选）
如果后续网络稳定，想恢复默认行为：

```bash
git config --unset http.version
```

## 备注
- 该问题通常是传输层问题，不代表提交内容有冲突或损坏。
- 若持续失败，可优先改用 SSH 远端或更稳定网络环境重试。
