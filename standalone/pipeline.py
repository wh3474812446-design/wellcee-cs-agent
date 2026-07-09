# -*- coding: utf-8 -*-
"""Wellcee 小Cee 智能客服 —— 无框架纯代码实现（教学版）

与 Dify 版（workflow/wellcee-xiaocee.yml）逻辑等价：同一套四层 DAG、同源 prompt。
依赖：仅 `pip install openai`。运行：设置环境变量 DEEPSEEK_API_KEY 后 `python pipeline.py`
架构讲解见《编排框架教学-从Dify到代码.md》第三课。

四层结构：
  确定性预处理（语言检测/高风险规则） → 路由（LLM 意图分类） → 处置（六分支） → 输出（流式）
"""
import os
import csv
import json
import math
from collections import Counter
from openai import OpenAI

# ==================== 配置 ====================
client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
)
FLASH = "deepseek-v4-flash"   # 判别类任务：分类、参数提取（快、便宜）
PRO = "deepseek-v4-pro"       # 生成类任务：面向用户的回答（表达质量好）
# DeepSeek V4 系列默认开思考模式，思维链会混进回答文本，必须显式关闭
# （若你的 API 版本不支持该参数，删除 extra_body 即可）
NO_THINK = {"thinking": False}


def chat(model, system, user, history=None, temperature=0.3, stream=False):
    """所有 LLM 调用的唯一出口（对应 Dify 的 LLM 节点）。history 即 Dify 的 memory。"""
    msgs = [{"role": "system", "content": system}]
    if history:
        msgs += history[-20:]  # 记忆窗口 10 轮（user+assistant 各算一条）
    msgs.append({"role": "user", "content": user})
    resp = client.chat.completions.create(
        model=model, messages=msgs, temperature=temperature,
        stream=stream, extra_body=NO_THINK,
    )
    if stream:
        return resp
    return resp.choices[0].message.content


# ==================== 0. 知识库与检索（对应 Dify 知识检索节点） ====================
class Retriever:
    """字符 bigram 余弦相似度检索。

    教学要点：检索的本质是相似度排序。54 条知识库量级用不着向量数据库——
    生产替换点：把 _vec() 换成 embedding API（bge / text-embedding-3），
    search() 的接口签名不变，上层代码零改动。
    """

    def __init__(self, csv_path):
        self.entries = []  # [(question, answer, vec)]
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                q, a = row["question"], row["answer"]
                self.entries.append((q, a, self._vec(q + " " + a[:80])))

    @staticmethod
    def _vec(text):
        t = text.lower()
        return Counter(t[i:i + 2] for i in range(len(t) - 1))

    @staticmethod
    def _cos(v1, v2):
        common = set(v1) & set(v2)
        dot = sum(v1[k] * v2[k] for k in common)
        n1 = math.sqrt(sum(x * x for x in v1.values()))
        n2 = math.sqrt(sum(x * x for x in v2.values()))
        return dot / (n1 * n2) if n1 and n2 else 0.0

    def search(self, query, top_k=3, threshold=0.12):
        qv = self._vec(query)
        scored = sorted(
            ((self._cos(qv, vec), q, a) for q, a, vec in self.entries),
            reverse=True,
        )
        return [(q, a, s) for s, q, a in scored[:top_k] if s >= threshold]


def format_context(hits):
    if not hits:
        return "（无相关检索结果）"
    return "\n\n".join(f"[条目] {q}\n{a}" for q, a, _ in hits)


# ==================== 1. 确定性预处理层 ====================
def detect_lang(query):
    """对应 Dify 语言检测代码节点：字符占比判断，零成本零延迟。"""
    zh = sum(1 for c in query if "一" <= c <= "鿿")
    return "zh" if zh / max(len(query.strip()), 1) > 0.15 else "en"


RISK_WORDS = ["举报", "被骗", "骗子", "诈骗", "冒充", "投诉", "不给退", "退不了",
              "报警", "人工", "scam", "fraud", "report", "human agent"]


def risk_hit(query):
    """对应 Dify 高风险规则 if-else 节点：强信号词直接旁路，不赌 LLM 分类。"""
    return any(w in query.lower() for w in RISK_WORDS)


# ==================== 2. 路由层（对应 Dify 问题分类器节点） ====================
INTENT_DEFS = """faq_direct：询问平台规则、功能说明、费用、安全性、原因解释等有标准答案的问题。例：押金托管规则、怎么联系房东、收不到验证码、平台怎么收费、为什么要认证、房东不回复/不理我怎么办、房源没人看/没曝光怎么办、landlord not replying
process_guide：询问"怎么操作、怎么办"的流程类问题，需要分步指导。例：线上签约怎么走、押金怎么退、怎么发布房源、学生认证怎么做
tool_deposit：查询自己这笔押金的退还状态或进度。例：我的押金退了吗、押金什么时候到账、帮我查下订单
human_handoff：举报、纠纷、申诉、账号安全（换绑/注销）等必须人工处理的问题。注意：单纯的房东不回复消息、房源曝光低属于 faq_direct，不属于本类
chitchat：打招呼、闲聊、询问你是谁/是不是机器人、夸奖或吐槽助手本身
unclear：表述模糊无法判断在问什么，或不属于以上任何类别"""

VALID_INTENTS = {"faq_direct", "process_guide", "tool_deposit",
                 "human_handoff", "chitchat", "unclear"}


def classify(query):
    """三层防线让概率输出变成可靠路由信号：JSON mode → 枚举校验 → 失败落 unclear。"""
    system = ("你是意图分类器。根据类别定义，把用户消息归入唯一类别。\n"
              f"类别定义：\n{INTENT_DEFS}\n"
              '只输出 JSON：{"intent": "<类别名>"}')
    try:
        raw = client.chat.completions.create(
            model=FLASH, temperature=0.1, extra_body=NO_THINK,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": query}],
        ).choices[0].message.content
        intent = json.loads(raw).get("intent", "unclear")
        return intent if intent in VALID_INTENTS else "unclear"
    except Exception:
        return "unclear"


# ==================== 3. 处置层（prompt 与 Dify 版逐字同源） ====================
def sys_prefix(lang):
    return f"""你是小Cee，Wellcee（唯心所寓）的 AI 智能客服助手。Wellcee 是无中介费的房东直租+社交租房平台，覆盖 40+ 城市、用户来自 170+ 国家。

【人设】年轻、友好、专业、有温度；适度使用 emoji（每条不超过 2 个）；称呼用户"你"。

【语言】lang={lang}。zh → 简体中文回答；en → 英文回答。用户中英夹杂时跟随其主要语言。

【红线（任何情况下不可违反）】
1. 金额、押金、退款时效、法律责任类信息：只能使用知识库/检索结果/查询结果中的原文，禁止编造或自行估算
2. 禁止承诺性/结论性表述："一定、保证、肯定能退、他确实是骗子"等
3. 时效类回答必须带限定语（"以实际到账为准，超时请转人工核查"）
4. 不评价纠纷双方对错，不预测处理结果
5. 被问身份时明示自己是 AI 助手
6. 答不了就诚实说，并给转人工路径；禁止编造

"""


def handle_faq(query, lang, retriever, stream=True):
    ctx = format_context(retriever.search(query))
    system = sys_prefix(lang) + f"""【本节点任务】仅基于下方检索结果回答用户问题。
规则：
- 答案内容必须完全来自检索结果，禁止补充检索结果之外的事实
- 若检索结果为空或与问题无关：诚实告知"这个问题我暂时没有可靠资料"，给出两条路径（点击"转人工"/换个说法再问），禁止编造，此时**不要**输出来源行
- 来源标注规则：仅当答案的主体事实来自检索结果时才在末尾标注来源；一般性建议或常识不标来源。标签跟随回答语言——中文「📖 来源：<条目问题>」，英文「📖 Source: <entry question>」
- 涉及金额/时效：使用原文表述并附限定语
检索结果：{ctx}"""
    return chat(PRO, system, query, stream=stream)


def handle_guide(query, lang, retriever, history, stream=True):
    ctx = format_context(retriever.search(query))
    system = sys_prefix(lang) + f"""【本节点任务】用户在问操作流程。基于检索结果把流程拆成编号步骤，分步引导，不一次灌完。
规则：
- 第一轮：先确认关键分支条件（例：押金问题先问"是否走了线上签约？"；发布问题先确认角色），给对应路径的第 1-2 步，末尾问"继续吗？"
- 用户确认后再给后续步骤
- 每步一句话说清：在哪个页面、点什么、会看到什么
- 检索结果覆盖不了的步骤细节，明说"这一步的具体入口以 App 实际界面为准"，不编造按钮名
检索结果：{ctx}"""
    return chat(PRO, system, query, history=history, stream=stream)


def extract_order_id(query):
    """对应 Dify 参数提取器节点。"""
    try:
        raw = client.chat.completions.create(
            model=FLASH, temperature=0.1, extra_body=NO_THINK,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content":
                       '提取用户消息中的订单号（一串数字）。没有则为空字符串。只输出 JSON：{"order_id": "..."}'},
                      {"role": "user", "content": query}],
        ).choices[0].message.content
        return json.loads(raw).get("order_id", "")
    except Exception:
        return ""


def mock_deposit_query(order_id):
    """对应 Dify mock押金查询代码节点（与 Dify 版逐字相同）：订单尾号决定状态，演示可控。"""
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


def handle_tool(query, lang, stream=True):
    r = mock_deposit_query(extract_order_id(query))
    system = sys_prefix(lang) + f"""【本节点任务】根据查询结果回复用户押金状态。
查询结果：found={r['found']}，status={r['status']}，eta={r['eta']}，amount={r['amount']} 元
规则：
- found=none（用户没给订单号）：请用户提供订单号（在 App「我的-我的签约」可查看），不要瞎猜
- found=no：告知未查到该订单，请核对订单号，或点"转人工"人工核查
- found=yes：报状态；金额、时效必须原样引用查询结果字段；附"以实际到账为准"
- status=退款处理中：加一句"超过 3 个工作日未到账，随时转人工帮你核查\""""
    return chat(PRO, system, query, stream=stream)


def handle_handoff(query, lang, history, stream=True):
    """用 prompt 实现的槽位填充状态机：必收字段=槽位，"对照历史不重复问"=状态检查。"""
    system = sys_prefix(lang) + """【本节点任务】用户的问题需要人工处理（举报/纠纷/申诉/账号安全/主动要人工）。你负责：共情 → 收集信息 → 生成工单摘要。你不解决问题本身，也绝不下结论。
必收字段：① 问题类型 ② 对方昵称或房源链接（如涉及他人）③ 订单号（如涉及押金/签约）④ 用户诉求 ⑤ 证据说明（有无聊天记录/转账凭证等截图）
规则：
- 【最高优先级】用户提及被骗/资金损失时，第一轮回复必须同时包含：① 提醒保留转账凭证与聊天记录 ② 建议报警。禁止预测追回结果
- 开场先共情一句；只陈述平台会核实处理，禁止"他确实是中介/肯定能退"类判断
- 对照对话历史：已提供的字段不重复问；一次只问 1-2 个缺失字段
- 字段收齐后输出工单摘要（📋 工单摘要（草稿）：问题类型/涉及对象或订单/用户诉求/证据/对话要点）并请用户确认
- 用户确认后：告知已提交，人工客服预计 1-2 个工作日内跟进（以实际为准），安抚收尾"""
    return chat(PRO, system, query, history=history, stream=stream)


def handle_chitchat(query, lang, stream=True):
    system = sys_prefix(lang) + """【本节点任务】用户在闲聊或问你身份。按人设简短回应（不超过 2 句），然后自然引导回业务，例如："有什么租房相关的问题我可以帮你？😊"
被问"你是人工吗/机器人吗"：明确说明自己是 AI 助手小Cee，复杂问题可以随时转人工。"""
    return chat(FLASH, system, query, temperature=0.7, stream=stream)


CLARIFY_TEXT = """我想先确认一下你想办的事，这样能直接给你准确答案～你想问的是：
1️⃣ 押金 / 退款相关
2️⃣ 找房 / 联系房东
3️⃣ 房源发布 / 审核（我是房东）
4️⃣ 举报 / 纠纷
5️⃣ 都不是——直接换个说法描述，或回复「人工」转人工客服"""


# ==================== 4. 编排主循环（对应 Dify 的连线） ====================
def respond(query, session, retriever):
    """路由 = 一个 if/else + dict，这就是 Dify 画布上全部连线的代码形态。"""
    lang = detect_lang(query)
    if risk_hit(query):                       # 高风险规则旁路（先于 LLM 分类）
        route = "human_handoff(规则旁路)"
        out = handle_handoff(query, lang, session["history"])
    else:
        intent = classify(query)
        route = intent
        if intent == "faq_direct":
            out = handle_faq(query, lang, retriever)
        elif intent == "process_guide":
            out = handle_guide(query, lang, retriever, session["history"])
        elif intent == "tool_deposit":
            out = handle_tool(query, lang)
        elif intent == "human_handoff":
            out = handle_handoff(query, lang, session["history"])
        elif intent == "chitchat":
            out = handle_chitchat(query, lang)
        else:                                  # unclear：固定文案，不走 LLM
            out = CLARIFY_TEXT
    return out, route


def main():
    # 知识库 CSV 的候选位置（standalone/ 同级或仓库结构）
    for p in ("../dify-import-kb.csv", "../knowledge-base/dify-import-kb.csv", "dify-import-kb.csv"):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
        if os.path.exists(path):
            retriever = Retriever(path)
            break
    else:
        raise SystemExit("找不到 dify-import-kb.csv，请放到脚本同级或上级目录")

    print(f"小Cee 纯代码版已就绪（知识库 {len(retriever.entries)} 条）。输入 q 退出。\n")
    session = {"history": []}
    while True:
        query = input("你：").strip()
        if not query or query.lower() == "q":
            break
        out, route = respond(query, session, retriever)
        print(f"  [路由: {route}]")
        if isinstance(out, str):               # 固定文案分支
            answer = out
            print(f"小Cee：{answer}\n")
        else:                                  # 流式输出
            print("小Cee：", end="", flush=True)
            chunks = []
            for ev in out:
                delta = ev.choices[0].delta.content or ""
                chunks.append(delta)
                print(delta, end="", flush=True)
            answer = "".join(chunks)
            print("\n")
        session["history"] += [{"role": "user", "content": query},
                               {"role": "assistant", "content": answer}]


if __name__ == "__main__":
    main()
