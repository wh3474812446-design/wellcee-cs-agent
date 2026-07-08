# Wellcee 品牌规范（brand-spec，huashu-design 资产协议产物）

> 来源优先级：App 真机截图实测（01-调研/screenshots/app-0*.png）> 官网提取 > 假设。2026-07-08 固化。

## 资产

| 资产 | 状态 | 路径/值 |
|------|------|---------|
| Logo（白色中英文官方 SVG） | ✅ 官网下载 | `04-原型与对话流/assets/wellcee_logo_white.svg`（4.9KB，原型内 base64 内嵌） |
| App UI 截图 | ✅ 真机实测 6 张 | `01-调研/screenshots/app-0*.png` |
| 网页版截图 | ✅ 3 张 | `01-调研/screenshots/0*.png` |

## 色板（从 App 深色模式截图提取）

| Token | 值 | 用途来源 |
|-------|-----|---------|
| `--bg-app` | #101917 | App 页面底色（截图 app-01/02 深墨绿黑） |
| `--bg-card` | #1C2624 | 卡片/列表项底色 |
| `--bg-elev` | #232F2C | 浮层/输入框 |
| `--teal` | #17A398 | 主行动色（"咨询客服"/"继续沟通"按钮） |
| `--teal-deep` | #0F8C7F | 渐变深端（会员卡） |
| `--text` | #E8EFED | 主文本（近白） |
| `--text-dim` | #8FA29D | 次要文本 |
| `--line` | rgba(255,255,255,0.07) | 分隔线 |
| `--danger` | #E5484D | 警示/举报 |

## 字体与气质

- App 内 UI：系统栈（-apple-system/PingFang SC）——原型贴 App 真实感，不引外部 display 字体
- 气质关键词：年轻、干净、治愈、国际化（截图里大量留白+低饱和深色+青绿点缀）
- 禁区：紫渐变、emoji 图标滥用、彩色左 border 卡片（AI slop 清单）；亮色模式（App 实测为深色）

## 原型 assumptions（Junior 模式声明）

1. 🔶 色值为截图目测提取（未拿到官方 design token），误差 ±5% 色相内
2. 🔶 "小Cee"助手命名借用其官方社区账号"小cee和她的朋友们"的既有 IP 叫法
3. 🔶 App 实际为混合开发（截图交互推断），原型按 iOS 15 Pro 规格呈现
