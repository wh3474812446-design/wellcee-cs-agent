# -*- coding: utf-8 -*-
"""自动化跑评测：批量打 Dify draft run API（经浏览器 CDP proxy），记录路由+回答
用法：python _tools/run_eval.py <evalset.json> <输出.json> [case_id,case_id,...只跑这些]
依赖：CDP proxy 运行中、Dify tab 存在且已登录
"""
import json, os, sys, io, subprocess, tempfile, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TARGET = "42B76B4B3D7562A115871299316B4A96"
APP = "59d18bec-61b8-458f-a217-a8c35efb4ff1"
BATCH = 1  # proxy 的 CDP Runtime.evaluate 有 30s 硬超时，单条 eval（15-20s）才能稳定通过

RUN_JS = """(async () => {
  const csrf = decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/) || [])[1] || "");
  const items = %s;
  const results = [];
  for (const it of items) {
    try {
      const r = await fetch("/console/api/apps/%s/advanced-chat/workflows/draft/run", {
        method: "POST", credentials: "include",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf},
        body: JSON.stringify({ query: it.q, inputs: {}, conversation_id: "", response_mode: "streaming", model_config: {} })
      });
      if (!r.ok) { results.push({id: it.id, err: "HTTP " + r.status}); continue; }
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "", answer = "", nodes = [];
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buf += dec.decode(value, {stream: true});
        const lines = buf.split("\\n");
        buf = lines.pop();
        for (const ln of lines) {
          if (!ln.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(ln.slice(6));
            if (ev.event === "message") answer += ev.answer || "";
            else if (ev.event === "node_finished" && ev.data) nodes.push(ev.data.title);
            else if (ev.event === "error") answer += "[[STREAM_ERR:" + (ev.message||"") + "]]";
          } catch(e) {}
        }
      }
      results.push({id: it.id, nodes, answer: answer.slice(0, 900)});
    } catch(e) { results.push({id: it.id, err: String(e).slice(0,150)}); }
  }
  return JSON.stringify(results);
})()
"""

def eval_js(js_text, timeout=300):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js_text); path = f.name
    try:
        out = subprocess.run(
            ["curl", "-s", "-X", "POST", f"http://127.0.0.1:3456/eval?target={TARGET}",
             "--data-binary", f"@{path}", "--max-time", str(timeout)],
            capture_output=True, timeout=timeout + 10)
        raw = out.stdout.decode("utf-8", errors="replace")
        try:
            return json.loads(raw)["value"]
        except Exception as e:
            raise RuntimeError(f"{e} | raw[:200]={raw[:200]!r}")
    finally:
        os.unlink(path)

def main():
    cases = json.load(open(sys.argv[1], encoding="utf-8"))
    out_path = sys.argv[2]
    if len(sys.argv) > 3:
        only = set(sys.argv[3].split(","))
        cases = [c for c in cases if c["id"] in only]
    print(f"total cases: {len(cases)}")
    all_results = []
    for i in range(0, len(cases), BATCH):
        batch = cases[i:i+BATCH]
        items = [{"id": c["id"], "q": c["q"]} for c in batch]
        js = RUN_JS % (json.dumps(items, ensure_ascii=False), APP)
        t0 = time.time()
        try:
            val = eval_js(js)
            got = json.loads(val) if val else []
        except Exception as e:
            got = [{"id": c["id"], "err": f"batch fail: {e}"} for c in batch]
        all_results.extend(got)
        ok = sum(1 for g in got if not g.get("err"))
        print(f"batch {i//BATCH+1}: {ok}/{len(batch)} ok, {time.time()-t0:.0f}s ({batch[0]['id']}-{batch[-1]['id']})")
        json.dump(all_results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        time.sleep(2)
    errs = [r["id"] for r in all_results if r.get("err")]
    print(f"DONE {len(all_results)} results -> {out_path}; errors: {errs or 'none'}")

if __name__ == "__main__":
    main()
