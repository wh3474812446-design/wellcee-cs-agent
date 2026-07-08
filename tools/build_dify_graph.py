# -*- coding: utf-8 -*-
"""生成 Dify Chatflow 完整 graph（对应《Dify搭建手册》11 节点设计）
输出：scratchpad/dify_push.js —— 在浏览器 eval 中执行：GET draft 取 hash → POST 完整 graph
用法：python _tools/build_dify_graph.py <app_id> <输出js路径>
"""
import json, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

APP_ID = sys.argv[1]
OUT = sys.argv[2]
PROVIDER = "langgenius/deepseek/deepseek"
# 2026-07-08 实测踩坑：deepseek 插件 0.0.19 下 V4 全系默认 thinking=true，<think> 段会泄漏进回答；
# 修法 = completion_params 显式 thinking:false（parameter-rules 查得）。生成节点用 pro（回答温度好），轻任务 flash
FLASH, PRO = "deepseek-v4-flash", "deepseek-v4-pro"
KB_ID = "15e8ac9d-0499-4ee9-929f-b6ba4f20dcce"

SYS_PREFIX = """你是小Cee，Wellcee（唯心所寓）的 AI 智能客服助手。Wellcee 是无中介费的房东直租+社交租房平台，覆盖 40+ 城市、用户来自 170+ 国家。

【人设】年轻、友好、专业、有温度；适度使用 emoji（每条不超过 2 个）；称呼用户"你"。

【语言】lang={{#lang_detect.lang#}}。zh → 简体中文回答；en → 英文回答。用户中英夹杂时跟随其主要语言。

【红线（任何情况下不可违反）】
1. 金额、押金、退款时效、法律责任类信息：只能使用知识库/检索结果/查询结果中的原文，禁止编造或自行估算
2. 禁止承诺性/结论性表述："一定、保证、肯定能退、他确实是骗子"等
3. 时效类回答必须带限定语（"以实际到账为准，超时请转人工核查"）
4. 不评价纠纷双方对错，不预测处理结果
5. 被问身份时明示自己是 AI 助手
6. 答不了就诚实说，并给转人工路径；禁止编造

"""

def model(name, temp=0.3):
    return {"provider": PROVIDER, "name": name, "mode": "chat",
            "completion_params": {"temperature": temp, "thinking": False}}

def node(nid, ntype, title, data, x, y, w=242, h=90):
    d = dict(data); d["type"] = ntype; d["title"] = title; d["selected"] = False; d["desc"] = ""
    return {"id": nid, "type": "custom", "data": d,
            "position": {"x": x, "y": y}, "positionAbsolute": {"x": x, "y": y},
            "targetPosition": "left", "sourcePosition": "right", "width": w, "height": h}

def llm_data(mdl, system_text, user_text="{{#sys.query#}}", ctx_selector=None, mem=False):
    d = {
        "model": mdl,
        "prompt_template": [{"role": "system", "text": system_text}, {"role": "user", "text": user_text}],
        "context": {"enabled": bool(ctx_selector), "variable_selector": ctx_selector or []},
        "vision": {"enabled": False},
    }
    if mem:
        d["memory"] = {"window": {"enabled": True, "size": 10},
                       "query_prompt_template": "{{#sys.query#}}",
                       "role_prefix": {"user": "", "assistant": ""}}
    return d

RISK_WORDS = ["举报", "被骗", "骗子", "诈骗", "冒充", "投诉", "不给退", "退不了", "报警", "人工",
              "scam", "fraud", "report", "human agent"]

nodes = []
edges = []

# ---- 主干 ----
nodes.append(node("start_n", "start", "开始", {"variables": []}, 60, 400, h=72))

nodes.append(node("lang_detect", "code", "语言检测", {
    "code_language": "python3",
    "code": "def main(query: str) -> dict:\n    zh = sum(1 for c in query if '\\u4e00' <= c <= '\\u9fff')\n    ratio = zh / max(len(query.strip()), 1)\n    return {\"lang\": \"zh\" if ratio > 0.15 else \"en\"}\n",
    "variables": [{"variable": "query", "value_selector": ["sys", "query"]}],
    "outputs": {"lang": {"type": "string", "children": None}},
}, 340, 400))

conds = [{"id": f"rw{i}", "varType": "string", "variable_selector": ["sys", "query"],
          "comparison_operator": "contains", "value": w} for i, w in enumerate(RISK_WORDS)]
nodes.append(node("risk_check", "if-else", "高风险规则", {
    "cases": [{"case_id": "true", "logical_operator": "or", "conditions": conds}],
}, 620, 400))

# 2026-07-08 首轮评测修复 F1：例句补齐口语变体与英文（BC-1/2/3/4/7），human 加排除说明
CLASSES = [
    ("c_faq", "faq_direct：询问平台规则、功能说明、费用、安全性、原因解释等有标准答案的问题。例：押金托管规则、怎么联系房东、收不到验证码、平台怎么收费、为什么要认证、房东不回复/不理我怎么办、房源没人看/没曝光怎么办、landlord not replying"),
    ("c_guide", "process_guide：询问\"怎么操作、怎么办\"的流程类问题，需要分步指导。例：线上签约怎么走、押金怎么退、怎么发布房源、学生认证怎么做"),
    ("c_tool", "tool_deposit：查询自己这笔押金的退还状态或进度。例：我的押金退了吗、押金什么时候到账、帮我查下订单"),
    ("c_human", "human_handoff：举报、纠纷、申诉、账号安全（换绑/注销）等必须人工处理的问题。注意：单纯的房东不回复消息、房源曝光低属于 faq_direct，不属于本类"),
    ("c_chat", "chitchat：打招呼、闲聊、询问你是谁/是不是机器人、夸奖或吐槽助手本身"),
    ("c_unclear", "unclear：表述模糊无法判断在问什么，或不属于以上任何类别"),
]
nodes.append(node("classifier", "question-classifier", "意图分类", {
    "model": model(FLASH, 0.1),
    "query_variable_selector": ["sys", "query"],
    "classes": [{"id": cid, "name": name} for cid, name in CLASSES],
    "instruction": "", "topics": [], "vision": {"enabled": False},
}, 900, 400))

# ---- faq_direct 分支 ----
nodes.append(node("kr_faq", "knowledge-retrieval", "知识检索-FAQ", {
    "query_variable_selector": ["sys", "query"],
    "dataset_ids": [KB_ID],
    "retrieval_mode": "multiple",
    "multiple_retrieval_config": {"top_k": 3, "score_threshold": None, "reranking_enable": False},
}, 1200, 80))
nodes.append(node("llm_faq", "llm", "LLM-FAQ直答", {
    **llm_data(model(PRO), SYS_PREFIX + """【本节点任务】仅基于下方检索结果回答用户问题。
规则：
- 答案内容必须完全来自检索结果，禁止补充检索结果之外的事实
- 若检索结果为空或与问题无关：诚实告知"这个问题我暂时没有可靠资料"，给出两条路径（点击"转人工"/换个说法再问），禁止编造，此时**不要**输出来源行
- 来源标注规则：**仅当答案的主体事实来自检索结果时**才在末尾标注来源；如果你给的是一般性建议或常识（检索结果只是间接相关），不要标来源。标签跟随回答语言——中文「📖 来源：<条目问题>」，英文「📖 Source: <entry question>」
- 涉及金额/时效：使用原文表述并附限定语
检索结果：{{#context#}}""", ctx_selector=["kr_faq", "result"]),
}, 1480, 80))
nodes.append(node("ans_faq", "answer", "回复-FAQ", {"variables": [], "answer": "{{#llm_faq.text#}}"}, 1760, 80))

# ---- process_guide 分支 ----
nodes.append(node("kr_guide", "knowledge-retrieval", "知识检索-流程", {
    "query_variable_selector": ["sys", "query"],
    "dataset_ids": [KB_ID],
    "retrieval_mode": "multiple",
    "multiple_retrieval_config": {"top_k": 3, "score_threshold": None, "reranking_enable": False},
}, 1200, 240))
nodes.append(node("llm_guide", "llm", "LLM-流程引导", {
    **llm_data(model(PRO), SYS_PREFIX + """【本节点任务】用户在问操作流程。基于检索结果把流程拆成编号步骤，分步引导，不一次灌完。
规则：
- 第一轮：先确认关键分支条件（例：押金问题先问"是否走了线上签约？"；发布问题先确认角色），给对应路径的第 1-2 步，末尾问"继续吗？"
- 用户确认后再给后续步骤
- 每步一句话说清：在哪个页面、点什么、会看到什么
- 检索结果覆盖不了的步骤细节，明说"这一步的具体入口以 App 实际界面为准"，不编造按钮名
检索结果：{{#context#}}""", ctx_selector=["kr_guide", "result"], mem=True),
}, 1480, 240))
nodes.append(node("ans_guide", "answer", "回复-流程", {"variables": [], "answer": "{{#llm_guide.text#}}"}, 1760, 240))

# ---- tool_deposit 分支 ----
nodes.append(node("param_ext", "parameter-extractor", "提取订单号", {
    "model": model(FLASH, 0.1),
    "query": ["sys", "query"],
    "parameters": [{"name": "order_id", "type": "string", "required": False,
                    "description": "用户消息中的订单号，通常为一串数字；没有提供则为空字符串"}],
    "reasoning_mode": "prompt", "instruction": "", "vision": {"enabled": False},
}, 1200, 420))
nodes.append(node("mock_query", "code", "mock押金查询", {
    "code_language": "python3",
    "code": """def main(order_id: str) -> dict:
    oid = "".join(ch for ch in str(order_id or "") if ch.isdigit())
    if not oid:
        return {"found": "none", "status": "", "eta": "", "amount": ""}
    tail = int(oid[-1])
    if tail in (1, 2, 3):
        return {"found": "yes", "status": "托管中", "eta": "租期结束后可发起退还", "amount": "3000.00"}
    if tail in (4, 5, 6):
        return {"found": "yes", "status": "退款处理中", "eta": "预计 1-3 个工作日到账（以实际到账为准）", "amount": "3000.00"}
    if tail in (7, 8, 9):
        return {"found": "yes", "status": "已退回", "eta": "已退回原支付账户", "amount": "3000.00"}
    return {"found": "no", "status": "", "eta": "", "amount": ""}
""",
    "variables": [{"variable": "order_id", "value_selector": ["param_ext", "order_id"]}],
    "outputs": {"found": {"type": "string", "children": None}, "status": {"type": "string", "children": None},
                "eta": {"type": "string", "children": None}, "amount": {"type": "string", "children": None}},
}, 1480, 420))
nodes.append(node("llm_tool", "llm", "LLM-查询回复", {
    **llm_data(model(PRO), SYS_PREFIX + """【本节点任务】根据查询结果回复用户押金状态。
查询结果：found={{#mock_query.found#}}，status={{#mock_query.status#}}，eta={{#mock_query.eta#}}，amount={{#mock_query.amount#}} 元
规则：
- found=none（用户没给订单号）：请用户提供订单号（在 App「我的-我的签约」可查看），不要瞎猜
- found=no：告知未查到该订单，请核对订单号，或点"转人工"人工核查
- found=yes：报状态；金额、时效必须原样引用查询结果字段；附"以实际到账为准"
- status=退款处理中：加一句"超过 3 个工作日未到账，随时转人工帮你核查" """),
}, 1760, 420))
nodes.append(node("ans_tool", "answer", "回复-查询", {"variables": [], "answer": "{{#llm_tool.text#}}"}, 2040, 420))

# ---- human_handoff 分支 ----
nodes.append(node("llm_handoff", "llm", "LLM-转人工收集", {
    **llm_data(model(PRO), SYS_PREFIX + """【本节点任务】用户的问题需要人工处理（举报/纠纷/申诉/账号安全/主动要人工）。你负责：共情 → 收集信息 → 生成工单摘要。你不解决问题本身，也绝不下结论。
必收字段：① 问题类型 ② 对方昵称或房源链接（如涉及他人）③ 订单号（如涉及押金/签约）④ 用户诉求 ⑤ 证据说明（有无聊天记录/转账凭证等截图）
规则：
- **【最高优先级】用户提及被骗/资金损失时，第一轮回复必须同时包含：① 提醒保留转账凭证与聊天记录 ② 建议报警。禁止预测追回结果**
- 开场先共情一句；只陈述平台会核实处理，禁止"他确实是中介/肯定能退"类判断
- 对照对话历史：已提供的字段不重复问；一次只问 1-2 个缺失字段
- 字段收齐后输出工单摘要并请用户确认：
---
📋 工单摘要（草稿）
问题类型：
涉及对象/订单：
用户诉求：
证据：
对话要点：（一句话）
---
信息对吗？确认后我会转交人工客服跟进。
- 用户确认后：告知已提交，人工客服预计 1-2 个工作日内跟进（以实际为准），安抚收尾，并提醒后续可在工单里补充上传截图证据""", mem=True),
}, 1200, 620))
nodes.append(node("ans_handoff", "answer", "回复-转人工", {"variables": [], "answer": "{{#llm_handoff.text#}}"}, 1480, 620))

# ---- chitchat 分支 ----
nodes.append(node("llm_chat", "llm", "LLM-闲聊人设", {
    **llm_data(model(FLASH, 0.7), SYS_PREFIX + """【本节点任务】用户在闲聊或问你身份。按人设简短回应（不超过 2 句），然后自然引导回业务，例如："有什么租房相关的问题我可以帮你？😊"
被问"你是人工吗/机器人吗"：明确说明自己是 AI 助手小Cee，复杂问题可以随时转人工。"""),
}, 1200, 780))
nodes.append(node("ans_chat", "answer", "回复-闲聊", {"variables": [], "answer": "{{#llm_chat.text#}}"}, 1480, 780))

# ---- unclear 分支 ----
nodes.append(node("ans_clarify", "answer", "澄清反问", {"variables": [], "answer": """我想先确认一下你想办的事，这样能直接给你准确答案～你想问的是：
1️⃣ 押金 / 退款相关
2️⃣ 找房 / 联系房东
3️⃣ 房源发布 / 审核（我是房东）
4️⃣ 举报 / 纠纷
5️⃣ 都不是——直接换个说法描述，或回复「人工」转人工客服"""}, 1200, 920, h=140))

# ---- edges ----
def edge(src, tgt, src_handle="source", stype=None, ttype=None):
    return {"id": f"{src}-{src_handle}-{tgt}", "source": src, "sourceHandle": src_handle,
            "target": tgt, "targetHandle": "target", "type": "custom",
            "data": {"sourceType": stype, "targetType": ttype, "isInIteration": False}}

tmap = {n["id"]: n["data"]["type"] for n in nodes}
def E(src, tgt, handle="source"):
    edges.append(edge(src, tgt, handle, tmap[src], tmap[tgt]))

E("start_n", "lang_detect")
E("lang_detect", "risk_check")
E("risk_check", "llm_handoff", "true")
E("risk_check", "classifier", "false")
E("classifier", "kr_faq", "c_faq")
E("kr_faq", "llm_faq"); E("llm_faq", "ans_faq")
E("classifier", "kr_guide", "c_guide")
E("kr_guide", "llm_guide"); E("llm_guide", "ans_guide")
E("classifier", "param_ext", "c_tool")
E("param_ext", "mock_query"); E("mock_query", "llm_tool"); E("llm_tool", "ans_tool")
E("classifier", "llm_handoff", "c_human")
E("llm_handoff", "ans_handoff")
E("classifier", "llm_chat", "c_chat")
E("llm_chat", "ans_chat")
E("classifier", "ans_clarify", "c_unclear")

graph = {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.6}}

features = {
    "opening_statement": "Hi～我是小Cee，Wellcee 的 AI 助手 🤖 租房流程、押金托管、房源发布…都可以问我。复杂问题我会帮你转人工。\nHi, I'm Xiao Cee, Wellcee's AI assistant. Ask me anything about renting!",
    "suggested_questions": ["押金怎么退？", "房东不回复怎么办？", "How does deposit escrow work?", "怎么发布房源？"],
    "suggested_questions_after_answer": {"enabled": True},
    "text_to_speech": {"enabled": False, "voice": "", "language": ""},
    "speech_to_text": {"enabled": False},
    "retriever_resource": {"enabled": True},
    "sensitive_word_avoidance": {"enabled": False},
    "file_upload": {"enabled": False, "allowed_file_extensions": [".JPG", ".JPEG", ".PNG", ".GIF", ".WEBP", ".SVG"],
                    "allowed_file_types": ["image"], "allowed_file_upload_methods": ["local_file", "remote_url"],
                    "image": {"enabled": False, "number_limits": 3, "transfer_methods": ["local_file", "remote_url"]},
                    "number_limits": 3},
}

payload = {"graph": graph, "features": features, "environment_variables": [], "conversation_variables": []}

js = """(async () => {
  window.__api = window.__api || (async (path, opts = {}) => {
    const csrf = decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/) || [])[1] || "");
    const headers = Object.assign({"X-CSRF-Token": csrf}, opts.body && typeof opts.body === "string" ? {"Content-Type": "application/json"} : {}, opts.headers || {});
    const r = await fetch("/console/api" + path, Object.assign({credentials: "include"}, opts, {headers}));
    const t = await r.text();
    try { return {s: r.status, j: JSON.parse(t)}; } catch(e) { return {s: r.status, t: t.slice(0,300)}; }
  });
  const appId = "%s";
  const cur = await window.__api("/apps/" + appId + "/workflows/draft");
  const payload = %s;
  payload.hash = cur.j.hash;
  const r = await window.__api("/apps/" + appId + "/workflows/draft", { method: "POST", body: JSON.stringify(payload) });
  return JSON.stringify({getHash: cur.s, post: r.s, resp: r.j || r.t}).slice(0, 500);
})()
""" % (APP_ID, json.dumps(payload, ensure_ascii=False))

open(OUT, "w", encoding="utf-8").write(js)
print(f"OK nodes={len(nodes)} edges={len(edges)} -> {OUT}")
