#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, random
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOPICS = [
    ("Agent runtimes", ["agent runtime", "computer use", "tool calling", "state machines", "MCP", "automation"]),
    ("Apple silicon", ["M1 Max", "Metal", "MLX", "Core ML", "ANE", "unified memory"]),
    ("Graphics engines", ["WebGPU", "Vello", "wgpu", "rendering", "shaders", "Rust graphics"]),
    ("Operating systems", ["kernel", "microVM", "hypervisor", "drivers", "scheduler", "memory manager"]),
    ("Local models", ["Qwen", "embedding models", "quantization", "inference", "system 1", "VLM"]),
    ("Startup craft", ["distribution", "product strategy", "growth", "founder", "GTM", "pricing"]),
    ("Computing history", ["transistors", "CPU", "Unix", "internet", "GPU", "personal computer"]),
    ("Robotics", ["robotics", "control", "embodied AI", "sensors", "actuators", "planning"]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--count", type=int, default=1100)
    args = ap.parse_args()
    random.seed(42)
    centers = []
    for i in range(len(TOPICS)):
        a = i / len(TOPICS) * math.tau
        centers.append((math.cos(a) * 58, math.sin(a) * 46, math.sin(a * 2.3) * 32))
    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    items=[]
    by_topic=[[] for _ in TOPICS]
    for i in range(args.count):
        c=i % len(TOPICS) if random.random() < .72 else random.randrange(len(TOPICS))
        label, words=TOPICS[c]
        cx,cy,cz=centers[c]
        bridge = random.random() < .08
        if bridge:
            c2=(c+random.randint(1,len(TOPICS)-1))%len(TOPICS)
            c2x,c2y,c2z=centers[c2]
            t=random.uniform(.25,.75)
            cx,cy,cz=(cx*(1-t)+c2x*t, cy*(1-t)+c2y*t, cz*(1-t)+c2z*t)
        x=cx+random.gauss(0,10); y=cy+random.gauss(0,9); z=cz+random.gauss(0,8)
        when=start+timedelta(days=random.randint(0,2050), hours=random.randint(0,23))
        word=random.choice(words); other=random.choice(words)
        title=f"{word.title()}: {random.choice(['from first principles','deep dive','what changed','explained','building it','the missing layer'])} — {other}"
        watches=1+int(random.random()**5*12)
        vid=f"demo{i:05d}"
        item={
            "id":vid,"source":"youtube","kind":"video","title":title,"url":"https://www.youtube.com/",
            "channel":random.choice(["Systems Lab","Low Level Learning","AI Engineering","Computerphile","Build Mode","Research Notes"]),
            "channelUrl":None,"watchCount":watches,"watchedAt":[when.isoformat()],"firstWatched":when.isoformat(),"lastWatched":when.isoformat(),
            "details":[],"x":round(x,5),"y":round(y,5),"z":round(z,5),"cluster":c,"clusterLabel":label,"related":[]
        }
        items.append(item); by_topic[c].append(i)
    for i,item in enumerate(items):
        candidates=by_topic[item["cluster"]]
        item["related"]=[items[j]["id"] for j in random.sample(candidates,min(6,len(candidates))) if j!=i][:6]
    clusters=[]
    for c,(label,_) in enumerate(TOPICS):
        inds=by_topic[c]; pts=[items[i] for i in inds]
        center=[sum(p[a] for p in pts)/len(pts) for a in ("x","y","z")]
        clusters.append({"id":c,"label":label,"count":len(inds),"center":[round(v,5) for v in center]})
    payload={
        "version":1,"generatedAt":datetime.now(timezone.utc).isoformat(),
        "meta":{"eventCount":sum(x["watchCount"] for x in items),"videoCount":len(items),"clusterCount":len(clusters),"embedder":"demo","projection":"synthetic","sourceFiles":[],"minTime":min(x["firstWatched"] for x in items),"maxTime":max(x["lastWatched"] for x in items)},
        "clusters":clusters,"items":items,
    }
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,separators=(",",":")))
    print(f"wrote demo galaxy: {out} ({len(items)} points)")
if __name__=="__main__": main()
