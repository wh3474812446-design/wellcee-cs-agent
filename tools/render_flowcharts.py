# -*- coding: utf-8 -*-
"""从 md 提取 mermaid 块 → 每图生成单页 HTML（供浏览器截图）
用法：python _tools/render_flowcharts.py <md文件>
输出：_tools/render_fig1.html / render_fig2.html / render_fig3.html
"""
import re, sys, os, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TITLES = [
    "图① 押金怎么退（A6 ｜ 流程引导 + 工具调用）",
    "图② 房东不回复（A3 ｜ 安抚型流程引导）",
    "图③ 举报中介冒充房东（A9 ｜ 必转人工 + 内容审核联动）",
]

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>fig</title>
<style>
  body {{ background:#fff; font-family:"PingFang SC","Microsoft YaHei",sans-serif; margin:0; padding:28px 32px; width:fit-content; }}
  h2 {{ font-size:18px; color:#0F5A52; margin:0 0 4px; }}
  .sub {{ font-size:12px; color:#8FA29D; margin:0 0 16px; }}
  .mermaid {{ background:#fff; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
</head>
<body>
<h2>{title}</h2>
<p class="sub">Wellcee 智能客服 Agent · 对话流设计 · 2026-07</p>
<pre class="mermaid">
{src}
</pre>
<script>
  mermaid.initialize({{
    startOnLoad: true, theme: 'base',
    themeVariables: {{
      primaryColor: '#F4FAF9', primaryBorderColor: '#17A398',
      primaryTextColor: '#1C2624', lineColor: '#5B7470',
      fontSize: '14px',
      fontFamily: '"PingFang SC","Microsoft YaHei",sans-serif'
    }},
    flowchart: {{ curve: 'basis', nodeSpacing: 40, rankSpacing: 48, useMaxWidth: false }}
  }});
  window.addEventListener('load', () => setTimeout(() => {{ document.title = 'RENDER_DONE'; }}, 1200));
</script>
</body>
</html>
"""

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

md_path = sys.argv[1]
tools_dir = os.path.dirname(os.path.abspath(__file__))
text = open(md_path, encoding="utf-8").read()
blocks = re.findall(r"```mermaid\n(.*?)```", text, re.S)
print(f"found {len(blocks)} mermaid blocks")
for i, src in enumerate(blocks, 1):
    out = os.path.join(tools_dir, f"render_fig{i}.html")
    open(out, "w", encoding="utf-8").write(
        PAGE.format(title=TITLES[i-1] if i <= len(TITLES) else f"图{i}", src=esc(src.strip())))
    print("wrote", out)
