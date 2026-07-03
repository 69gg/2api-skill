#!/usr/bin/env bash
# check_mcp.sh — 通用检测 context7 / chrome-devtools 两个 MCP server 是否已配置。
# 平台无关：不依赖任何特定 agent 的 CLI，只扫常见 MCP 配置文件位置。
# 用法： bash scripts/check_mcp.sh
# 退出码：0 = 两个都已配置；1 = 有缺失（并在 stdout 打印配置指引）。
set -o pipefail

SERVERS="context7 chrome-devtools"

# 收集候选配置文件：用户级 ~/.claude.json、向上查找的项目级 .mcp.json、~/.claude/settings.json
mapfile -t CANDIDATES < <(
  [ -f "$HOME/.claude.json" ] && printf '%s\n' "$HOME/.claude.json"
  d="$PWD"
  while [ "$d" != "/" ]; do
    [ -f "$d/.mcp.json" ] && printf '%s\n' "$d/.mcp.json"
    d="$(dirname "$d")"
  done
  [ -f "$HOME/.claude/settings.json" ] && printf '%s\n' "$HOME/.claude/settings.json"
  true
)

python3 - "$SERVERS" "${CANDIDATES[@]}" <<'PY'
import json, sys

servers = sys.argv[1].split()
candidates = sys.argv[2:]

DEFAULTS = {
    "context7": {"command": "npx", "args": ["-y", "@upstash/context7-mcp"]},
    "chrome-devtools": {"command": "npx", "args": ["-y", "chrome-devtools-mcp@latest", "--autoConnect"]},
}

found = {s: None for s in servers}

def collect_pools(data):
    """从一份配置 JSON 里挖出所有 mcpServers 池（顶层 + projects.<*> 下）。"""
    pools = []
    if isinstance(data, dict):
        top = data.get("mcpServers")
        if isinstance(top, dict):
            pools.append(top)
        projects = data.get("projects")
        if isinstance(projects, dict):
            for v in projects.values():
                if isinstance(v, dict) and isinstance(v.get("mcpServers"), dict):
                    pools.append(v["mcpServers"])
    return pools

for path in candidates:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        continue
    for pool in collect_pools(data):
        for s in servers:
            if s in pool and found[s] is None:
                found[s] = path

print("MCP 可用性检查：")
all_ok = True
for s in servers:
    if found[s]:
        print(f"  [OK] {s:<16} 已配置  ({found[s]})")
    else:
        all_ok = False
        print(f"  [--] {s:<16} 未在常见配置位置找到")

if not all_ok:
    missing = [s for s in servers if not found[s]]
    print()
    print(f"缺失：{', '.join(missing)}。任选一种方式补配置：")
    print()
    print("  方式 A · 项目级 .mcp.json（团队共享，推荐）：在项目根创建")
    print('  {')
    print('    "mcpServers": {')
    for s in missing:
        print(f'      "{s}": {json.dumps(DEFAULTS[s], ensure_ascii=False)},')
    print('    }')
    print('  }')
    print()
    print("  方式 B · 用户级：写入 ~/.claude.json 的 mcpServers（Claude Code），")
    print("          或你所用 agent 平台对应的 MCP 配置位置。")
    print()
    print("  方式 C · 若用 Claude Code CLI：")
    print("    claude mcp add context7 -- npx -y @upstash/context7-mcp")
    print("    claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest --autoConnect")
    print()
    print("  ⚠️  配置后需重启 agent（如 Claude Code）才生效。")
    print("  ℹ️  本 skill 可降级运行：context7 缺失→用 WebSearch 查文档；")
    print("     chrome-devtools 缺失→手动在浏览器 DevTools 抓包，喂给 scripts/request_to_curl.py。")

sys.exit(0 if all_ok else 1)
PY
