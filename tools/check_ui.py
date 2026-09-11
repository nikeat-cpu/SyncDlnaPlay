#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
静态校验 Web 界面：
  1. 抽出 index.html 里的内联 JS，交给 node --check 做语法检查
  2. 抽出 JS 调用的 API 路径，与 server.py 注册的路由做交叉比对
  3. 抽出 JS 里 getElementById 用到的元素 id，与 HTML 里的 id 比对
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "app", "static", "index.html")
SERVER = os.path.join(ROOT, "app", "server.py")

html = open(HTML, encoding="utf-8").read()
srv = open(SERVER, encoding="utf-8").read()

print("=" * 62)
print("Web 界面静态校验")
print("=" * 62)

# ---------- 1. JS 语法 ----------
scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
print(f"\n[1] 内联 <script> 块: {len(scripts)} 个")

tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_check.js")
ok_syntax = True
for i, s in enumerate(scripts):
    open(tmp, "w", encoding="utf-8").write(s)
    node = "node"
    r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"    script[{i}] 语法 OK ({len(s)} 字符)")
    else:
        ok_syntax = False
        print(f"    script[{i}] 语法错误:")
        print("      " + (r.stderr or "").strip().replace("\n", "\n      ")[:600])
if os.path.exists(tmp):
    os.remove(tmp)

# ---------- 2. API 路径比对 ----------
js = "\n".join(scripts)

# JS 里出现的 /api/xxx 字符串
js_apis = set(re.findall(r"['\"\`](/api/[A-Za-z0-9_\-/${}?.=&]+)", js))
# server.py 注册的路由
srv_routes = set(re.findall(r'@app\.route\(\s*["\']([^"\']+)["\']', srv))

# 把 Flask 风格 <path:filename> 归一化
def norm(p):
    return re.sub(r"<[^>]+>", "*", p)

srv_norm = {norm(r) for r in srv_routes}

print(f"\n[2] API 路径交叉比对")
print(f"    服务端注册路由 {len(srv_routes)} 条: {sorted(srv_routes)}")
print(f"    前端调用路径   {len(js_apis)} 条")

missing = []
for a in sorted(js_apis):
    base = a.split("?")[0]
    hit = any(base == s or base.startswith(s.rstrip("*")) and s.endswith("*")
              for s in srv_norm)
    if not hit:
        missing.append(a)

if missing:
    print("    ❌ 前端调用但服务端没有的路由:")
    for m in missing:
        print(f"       {m}")
else:
    print("    ✅ 前端调用的路径全部在服务端存在")

# 服务端有但前端没用到的（信息性）
unused = sorted(s for s in srv_routes
                if s.startswith("/api/") and s not in js_apis
                and not any(s.rstrip("*") in a for a in js_apis))
if unused:
    print(f"    ℹ️  服务端有但前端未直接调用（可能未被 UI 使用）: {unused}")

# ---------- 3. DOM id 比对 ----------
js_ids = set(re.findall(r"getElementById\(\s*['\"]([^'\"]+)['\"]", js))
html_ids = set(re.findall(r"\bid=\"([^\"]+)\"", html))
missing_ids = sorted(i for i in js_ids if i not in html_ids)

print(f"\n[3] DOM 元素 id 比对")
print(f"    JS 引用 id {len(js_ids)} 个 | HTML 定义 id {len(html_ids)} 个")
if missing_ids:
    print("    ❌ JS 引用但 HTML 中不存在的 id:")
    for m in missing_ids:
        print(f"       {m}")
else:
    print("    ✅ JS 引用的 id 全部在 HTML 中存在")

# ---------- 4. 常见隐患 ----------
print(f"\n[4] 隐患扫描")
issues = []
if "addEventListener('DOMContentLoaded'" not in js and "DOMContentLoaded" not in js:
    if "defer" not in html and "</body>" in html:
        # 脚本在 body 末尾即可，不算问题
        pass
if re.search(r"\bawait\s+", js) and not re.search(r"async\s+function", js):
    issues.append("JS 中出现 await 但没有 async function")
# 检查 fetch 是否用了相对路径（部署在子路径时会挂）
if re.search(r"fetch\(\s*['\"]/(api|)", js):
    issues.append("fetch 使用绝对路径 /api，若反向代理到子路径会失败（当前部署无影响）")
for fn in re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", js):
    pass

# 检查 onclick 引用的函数是否都已定义
onclick_fns = set(re.findall(r"on\w+=\"([A-Za-z_$][\w$]*)\(", html))
defined = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", js))
missing_fns = sorted(f for f in onclick_fns if f not in defined)
if missing_fns:
    print("    ❌ HTML onclick 引用但未定义的函数:")
    for f in missing_fns:
        print(f"       {f}()")
else:
    print(f"    ✅ HTML onclick 引用的 {len(onclick_fns)} 个函数均已定义")

if issues:
    for i in issues:
        print(f"    ⚠️  {i}")

print("\n" + "=" * 62)
print("结果:", "✅ 通过" if ok_syntax and not missing and not missing_ids and not missing_fns
      else "❌ 存在问题")
print("=" * 62)
