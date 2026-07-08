# -*- coding: utf-8 -*-
"""从 knowledge-base.xlsx 导出 Dify 知识库导入用 CSV（Q&A 两列，中英各一行）
用法：python _tools/export_dify_csv.py  （在项目根目录运行）
输出：06-Demo搭建/dify-import-kb.csv
"""
import csv, os, io, sys
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
df = pd.read_excel(os.path.join(root, "05-知识库", "knowledge-base.xlsx"), sheet_name="知识库总表")

out = os.path.join(root, "06-Demo搭建", "dify-import-kb.csv")
os.makedirs(os.path.dirname(out), exist_ok=True)

rows = []
for _, r in df.iterrows():
    # 🔶假设标记保留在答案里（红线：假设值必须显式可见），但去掉内部备注性括号说明
    rows.append((r["问题（中）"], r["答案（中）"]))
    rows.append((r["问题（英）"], r["答案（英）"]))

with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["question", "answer"])
    w.writerows(rows)

print(f"OK {out}  rows={len(rows)}")
