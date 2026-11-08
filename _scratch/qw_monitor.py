"""千问工作助理 · 对局监控脚本（只访问 HTTP 接口，不碰 src/ 源码）"""
import json, urllib.request

B = "http://127.0.0.1:8734"

def get(path):
    return json.load(urllib.request.urlopen(B + path))

def post(path, obj=None):
    data = json.dumps(obj or {}).encode()
    req = urllib.request.Request(B + path, data=data, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))

def brief(tag=""):
    s = get("/state")
    print(f"[{tag}] tick={s['tick']} elapsed={s['elapsed_seconds']}s "
          f"eq={s['equity']:.0f} bal={s['balance']:.0f} target={s['target']:.0f} "
          f"ML={s['margin_level']} finished={s['finished']} dq={s['disqualified']} "
          f"blowups={s['blowups']} ff={json.dumps(s['ff'], ensure_ascii=False)}")
    for p in s["positions"]:
        print("  ", p["pair"], p["side"], p["lots"], "手 upnl=", round(p["upnl"]))
    return s

if __name__ == "__main__":
    import sys
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    brief(tag)
