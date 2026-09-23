#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html as html_lib
import io
import json
import math
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Any
from urllib.parse import urlparse, parse_qs

import numpy as np
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import PCA, TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

WATCH_JSON_RE = re.compile(r"(?:^|/)(?:watch[-_ ]?history|MyActivity)\.json$", re.I)
WATCH_HTML_RE = re.compile(r"(?:^|/)(?:watch[-_ ]?history|MyActivity)\.html$", re.I)
YOUTUBE_HINT_RE = re.compile(r"youtube", re.I)
WATCH_WORD_RE = re.compile(r"^(Watched|Viewed)\s+", re.I)
SEARCH_WORD_RE = re.compile(r"^(Searched for|Visited)\s+", re.I)


@dataclass
class Event:
    title: str
    url: str | None
    video_id: str | None
    channel: str | None
    channel_url: str | None
    time: str | None
    timestamp: float | None
    details: list[str]
    products: list[str]
    source_file: str


def clean_title(raw: str | None) -> str:
    if not raw:
        return "Unknown video"
    s = html_lib.unescape(str(raw)).strip()
    s = WATCH_WORD_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip() or "Unknown video"


def parse_time(value: Any) -> tuple[str | None, float | None]:
    if not value:
        return None, None
    try:
        dt = date_parser.parse(str(value))
        if dt.tzinfo is None:
            iso = dt.isoformat()
        else:
            iso = dt.astimezone().isoformat()
        return iso, dt.timestamp()
    except Exception:
        return str(value), None


def video_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        if host in {"youtu.be", "www.youtu.be"}:
            vid = p.path.strip("/").split("/")[0]
            return vid or None
        if "youtube.com" in host or "youtube-nocookie.com" in host:
            q = parse_qs(p.query)
            if q.get("v"):
                return q["v"][0]
            parts = [x for x in p.path.split("/") if x]
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
                return parts[1]
    except Exception:
        pass
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{6,})", url)
    return m.group(1) if m else None


def looks_like_watch_json_entry(obj: dict[str, Any]) -> bool:
    title = str(obj.get("title") or "")
    controls = " ".join(map(str, obj.get("activityControls") or []))
    products = " ".join(map(str, obj.get("products") or []))
    header = str(obj.get("header") or "")
    if SEARCH_WORD_RE.match(title):
        return False
    if WATCH_WORD_RE.match(title):
        return True
    if "watch history" in controls.lower():
        return True
    return bool(obj.get("titleUrl") and "youtube" in (products + header + str(obj.get("titleUrl"))).lower())


def parse_json_bytes(data: bytes, source: str) -> list[Event]:
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except Exception as e:
        raise ValueError(f"Could not parse JSON {source}: {e}")

    if isinstance(payload, dict):
        # Some exports wrap activity in a key; tolerate common variants.
        for key in ("items", "activity", "activities", "events"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        return []

    out: list[Event] = []
    for obj in payload:
        if not isinstance(obj, dict) or not looks_like_watch_json_entry(obj):
            continue
        raw_title = obj.get("title")
        url = obj.get("titleUrl") or obj.get("url")
        subs = obj.get("subtitles") or []
        channel = channel_url = None
        if isinstance(subs, list) and subs:
            s0 = subs[0]
            if isinstance(s0, dict):
                channel = s0.get("name")
                channel_url = s0.get("url")
        details_raw = obj.get("details") or []
        details: list[str] = []
        if isinstance(details_raw, list):
            for d in details_raw:
                if isinstance(d, dict) and "name" in d:
                    details.append(str(d["name"]))
                elif isinstance(d, str):
                    details.append(d)
        products = [str(x) for x in (obj.get("products") or [])]
        iso, ts = parse_time(obj.get("time") or obj.get("time_usec") or obj.get("date"))
        out.append(Event(
            title=clean_title(raw_title),
            url=str(url) if url else None,
            video_id=video_id_from_url(str(url)) if url else None,
            channel=str(channel) if channel else None,
            channel_url=str(channel_url) if channel_url else None,
            time=iso,
            timestamp=ts,
            details=details,
            products=products,
            source_file=source,
        ))
    return out


def parse_html_bytes(data: bytes, source: str) -> list[Event]:
    soup = BeautifulSoup(data, "html.parser")
    out: list[Event] = []

    # Legacy Takeout uses repeated outer-cell activity cards. Falling back to broad
    # div matching lets this survive minor class changes.
    cards = soup.select("div.outer-cell") or soup.select("div.content-cell")
    if not cards:
        cards = [d for d in soup.find_all("div") if "Watched" in d.get_text(" ", strip=True)]

    seen_signatures: set[tuple[str, str | None, str | None]] = set()
    for card in cards:
        text = card.get_text(" ", strip=True)
        if not re.search(r"\b(Watched|Viewed)\b", text, re.I):
            continue
        if re.search(r"\bSearched for\b", text, re.I):
            continue
        links = card.find_all("a", href=True)
        video_link = None
        channel_link = None
        for a in links:
            href = str(a.get("href"))
            if video_link is None and video_id_from_url(href):
                video_link = a
            elif channel_link is None and "youtube.com/channel/" in href:
                channel_link = a
        if video_link is None:
            continue
        title = clean_title(video_link.get_text(" ", strip=True))
        url = str(video_link.get("href"))
        channel = channel_link.get_text(" ", strip=True) if channel_link else None
        channel_url = str(channel_link.get("href")) if channel_link else None

        # Takeout dates usually appear as plain text at the end of the card.
        # Try several timestamp-like fragments before accepting no time.
        iso = None
        ts = None
        candidates = re.findall(
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4},?\s+[^<]{4,40}?(?:GMT[+-]\d{1,2}:?\d{0,2}|UTC)?",
            text,
            re.I,
        )
        for c in reversed(candidates):
            i, t = parse_time(c)
            if t is not None:
                iso, ts = i, t
                break
        sig = (url, iso, channel)
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)
        out.append(Event(
            title=title,
            url=url,
            video_id=video_id_from_url(url),
            channel=channel,
            channel_url=channel_url,
            time=iso,
            timestamp=ts,
            details=[],
            products=["YouTube"],
            source_file=source,
        ))
    return out


def iter_candidate_files(path: Path) -> Iterator[tuple[str, bytes]]:
    if path.is_file() and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            preferred = [n for n in names if WATCH_JSON_RE.search(n) and YOUTUBE_HINT_RE.search(n)]
            legacy = [n for n in names if WATCH_HTML_RE.search(n) and YOUTUBE_HINT_RE.search(n)]
            my_activity = [n for n in names if WATCH_JSON_RE.search(n) and "my activity" in n.lower() and "youtube" in n.lower()]
            for n in preferred + legacy + my_activity:
                try:
                    yield n, zf.read(n)
                except Exception:
                    continue
        return

    if path.is_file():
        yield path.name, path.read_bytes()
        return

    if path.is_dir():
        candidates: list[Path] = []
        for p in path.rglob("*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(path)).replace(os.sep, "/")
            if (WATCH_JSON_RE.search(rel) or WATCH_HTML_RE.search(rel)) and "youtube" in rel.lower():
                candidates.append(p)
        for p in sorted(candidates):
            yield str(p.relative_to(path)), p.read_bytes()
        return

    raise FileNotFoundError(path)


def load_events(path: Path) -> tuple[list[Event], list[tuple[str, int]]]:
    all_events: list[Event] = []
    report: list[tuple[str, int]] = []
    for name, data in iter_candidate_files(path):
        lower = name.lower()
        try:
            if lower.endswith(".json"):
                events = parse_json_bytes(data, name)
            elif lower.endswith(".html"):
                events = parse_html_bytes(data, name)
            else:
                continue
        except Exception as e:
            print(f"warning: {name}: {e}", file=sys.stderr)
            continue
        if events:
            report.append((name, len(events)))
            all_events.extend(events)

    # If several candidate files cover the same export, remove exact duplicate events.
    dedup: dict[tuple[str | None, str, str | None], Event] = {}
    for e in all_events:
        key = (e.video_id or e.url, e.title, e.time)
        dedup[key] = e
    return list(dedup.values()), report


def aggregate_events(events: list[Event], exclude_music: bool = False) -> list[dict[str, Any]]:
    groups: dict[str, list[Event]] = defaultdict(list)
    for i, e in enumerate(events):
        if exclude_music:
            hay = " ".join([e.title, e.channel or "", *e.details, *e.products]).lower()
            if "youtube music" in hay or "music.youtube" in (e.url or "").lower():
                continue
        key = e.video_id or e.url or f"unknown:{e.title.lower()}"
        groups[key].append(e)

    videos: list[dict[str, Any]] = []
    for key, es in groups.items():
        es_sorted = sorted(es, key=lambda x: x.timestamp if x.timestamp is not None else -math.inf)
        exemplar = next((x for x in reversed(es_sorted) if x.video_id), es_sorted[-1])
        times = [x.time for x in es_sorted if x.time]
        timestamps = [x.timestamp for x in es_sorted if x.timestamp is not None]
        channels = Counter(x.channel for x in es if x.channel)
        channel = channels.most_common(1)[0][0] if channels else exemplar.channel
        videos.append({
            "id": exemplar.video_id or f"u{abs(hash(key))}",
            "source": "youtube",
            "kind": "video",
            "title": exemplar.title,
            "url": exemplar.url,
            "channel": channel,
            "channelUrl": exemplar.channel_url,
            "watchCount": len(es),
            "watchedAt": times,
            "firstWatched": es_sorted[0].time if es_sorted else None,
            "lastWatched": es_sorted[-1].time if es_sorted else None,
            "firstTs": min(timestamps) if timestamps else None,
            "lastTs": max(timestamps) if timestamps else None,
            "details": sorted({d for x in es for d in x.details}),
        })
    videos.sort(key=lambda v: (v["lastTs"] or -math.inf), reverse=True)
    return videos


def texts_for(videos: list[dict[str, Any]]) -> list[str]:
    out = []
    for v in videos:
        channel = v.get("channel") or ""
        # Repeating title slightly keeps its semantics more important than channel.
        out.append(f"{v['title']} {v['title']} channel {channel} {' '.join(v.get('details') or [])}")
    return out


def embed(texts: list[str], mode: str, model: str) -> tuple[np.ndarray, str, TfidfVectorizer]:
    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=2 if len(texts) > 100 else 1,
        max_df=0.97,
        max_features=30000,
        sublinear_tf=True,
    )
    tfidf = vectorizer.fit_transform(texts)

    actual = mode
    if mode == "auto":
        try:
            import sentence_transformers  # noqa: F401
            actual = "sentence-transformers"
        except Exception:
            actual = "tfidf"

    if actual == "sentence-transformers":
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise RuntimeError(
                "sentence-transformers is not installed. Run: .venv/bin/pip install -r requirements-semantic.txt"
            ) from e
        print(f"embedding {len(texts):,} videos with {model} ...")
        m = SentenceTransformer(model)
        arr = m.encode(texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True)
        return np.asarray(arr, dtype=np.float32), f"sentence-transformers:{model}", vectorizer

    # Compact semantic-ish fallback that has no model dependency.
    dims = min(192, max(2, tfidf.shape[1] - 1), max(2, len(texts) - 1))
    if dims < 3 or tfidf.shape[1] < 3:
        arr = tfidf.toarray().astype(np.float32)
    else:
        svd = TruncatedSVD(n_components=dims, random_state=42)
        arr = svd.fit_transform(tfidf).astype(np.float32)
    arr = normalize(arr)
    return arr, "tfidf-svd", vectorizer


def project3d(emb: np.ndarray, method: str) -> tuple[np.ndarray, str]:
    n = len(emb)
    if n <= 3:
        xyz = np.zeros((n, 3), dtype=np.float32)
        xyz[:, : min(emb.shape[1], 3)] = emb[:, : min(emb.shape[1], 3)]
        return xyz, "direct"

    if method in {"auto", "umap"}:
        try:
            import umap
            nn = min(30, max(5, int(math.sqrt(n))))
            reducer = umap.UMAP(
                n_components=3,
                n_neighbors=nn,
                min_dist=0.08,
                metric="cosine",
                random_state=42,
                low_memory=True,
            )
            xyz = reducer.fit_transform(emb)
            used = "umap"
        except Exception as e:
            if method == "umap":
                print(f"warning: UMAP failed ({e}); using PCA", file=sys.stderr)
            xyz = PCA(n_components=3, random_state=42).fit_transform(emb)
            used = "pca"
    else:
        xyz = PCA(n_components=3, random_state=42).fit_transform(emb)
        used = "pca"

    # Robust scale each axis around zero; keep outliers from flattening the galaxy.
    xyz = np.asarray(xyz, dtype=np.float32)
    xyz -= np.nanmedian(xyz, axis=0)
    p = np.nanpercentile(np.abs(xyz), 98, axis=0)
    p[p == 0] = 1
    xyz = np.clip(xyz / p, -1.2, 1.2) * 100.0
    return xyz, used


def cluster(emb: np.ndarray, requested_k: int | None) -> np.ndarray:
    n = len(emb)
    if n < 8:
        return np.zeros(n, dtype=int)
    k = requested_k or int(np.clip(round(math.sqrt(n / 2)), 6, 36))
    k = min(k, n)
    km = MiniBatchKMeans(n_clusters=k, random_state=42, batch_size=min(1024, max(64, n)), n_init="auto")
    return km.fit_predict(emb)


def cluster_labels(texts: list[str], labels: np.ndarray, vectorizer: TfidfVectorizer) -> dict[int, str]:
    matrix = vectorizer.transform(texts)
    terms = np.asarray(vectorizer.get_feature_names_out())
    result: dict[int, str] = {}
    for c in sorted(set(int(x) for x in labels)):
        idx = np.where(labels == c)[0]
        if len(idx) == 0:
            result[c] = f"Cluster {c+1}"
            continue
        scores = np.asarray(matrix[idx].mean(axis=0)).ravel()
        order = scores.argsort()[::-1]
        chosen: list[str] = []
        for j in order[:30]:
            term = terms[j]
            if len(term) < 3 or any(term in x or x in term for x in chosen):
                continue
            chosen.append(term)
            if len(chosen) == 3:
                break
        result[c] = " · ".join(chosen) if chosen else f"Cluster {c+1}"
    return result


def nearest_neighbors(emb: np.ndarray, k: int = 6) -> list[list[int]]:
    n = len(emb)
    if n == 0:
        return []
    # Blocked cosine to avoid materializing NxN for large histories.
    result: list[list[int]] = [[] for _ in range(n)]
    block = 512
    embn = normalize(emb)
    for start in range(0, n, block):
        end = min(n, start + block)
        sims = embn[start:end] @ embn.T
        for local, row in enumerate(np.asarray(sims)):
            i = start + local
            top = np.argpartition(row, -min(k + 1, n))[-min(k + 1, n):]
            top = top[np.argsort(row[top])[::-1]]
            result[i] = [int(j) for j in top if int(j) != i][:k]
    return result


def build(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.input).expanduser().resolve()
    events, report = load_events(source)
    if not events:
        raise RuntimeError("No YouTube watch-history entries found. Prefer a Takeout export with YouTube history in JSON format.")
    if args.limit:
        events = sorted(events, key=lambda e: e.timestamp or -math.inf, reverse=True)[: args.limit]
    videos = aggregate_events(events, exclude_music=args.exclude_music)
    if not videos:
        raise RuntimeError("History parsed, but no video records remained after filtering.")

    text = texts_for(videos)
    emb, embedder_used, vectorizer = embed(text, args.embedder, args.model)
    xyz, projection_used = project3d(emb, args.projection)
    labels = cluster(emb, args.clusters)
    label_names = cluster_labels(text, labels, vectorizer)
    neighbors = nearest_neighbors(emb, k=6)

    id_by_index = [v["id"] for v in videos]
    for i, v in enumerate(videos):
        v["x"], v["y"], v["z"] = [round(float(x), 5) for x in xyz[i]]
        v["cluster"] = int(labels[i])
        v["clusterLabel"] = label_names[int(labels[i])]
        v["related"] = [id_by_index[j] for j in neighbors[i]]
        # Keep payload compact.
        v.pop("firstTs", None)
        v.pop("lastTs", None)

    clusters = []
    for c in sorted(label_names):
        idx = np.where(labels == c)[0]
        center = xyz[idx].mean(axis=0) if len(idx) else np.zeros(3)
        clusters.append({
            "id": int(c),
            "label": label_names[c],
            "count": int(len(idx)),
            "center": [round(float(x), 5) for x in center],
        })

    all_ts = [e.timestamp for e in events if e.timestamp is not None]
    payload = {
        "version": 1,
        "generatedAt": datetime.now().astimezone().isoformat(),
        "meta": {
            "eventCount": len(events),
            "videoCount": len(videos),
            "clusterCount": len(clusters),
            "embedder": embedder_used,
            "projection": projection_used,
            "sourceFiles": [{"path": p, "events": n} for p, n in report],
            "minTime": datetime.fromtimestamp(min(all_ts)).astimezone().isoformat() if all_ts else None,
            "maxTime": datetime.fromtimestamp(max(all_ts)).astimezone().isoformat() if all_ts else None,
        },
        "clusters": clusters,
        "items": videos,
    }
    return payload


def inspect(args: argparse.Namespace) -> None:
    source = Path(args.input).expanduser().resolve()
    events, report = load_events(source)
    print(f"input: {source}")
    if not report:
        print("No recognized YouTube history files found.")
        return
    for p, n in report:
        print(f"{n:>8,}  {p}")
    print(f"{len(events):>8,}  unique parsed events")
    ids = sum(1 for e in events if e.video_id)
    times = sum(1 for e in events if e.timestamp is not None)
    channels = sum(1 for e in events if e.channel)
    print(f"video ids: {ids:,}  timestamps: {times:,}  channels: {channels:,}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a local semantic YouTube galaxy from Google Takeout.")
    ap.add_argument("input")
    ap.add_argument("--output", default="app/public/data/galaxy.json")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--embedder", choices=["auto", "tfidf", "sentence-transformers"], default="auto")
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    ap.add_argument("--projection", choices=["auto", "umap", "pca"], default="auto")
    ap.add_argument("--clusters", type=int)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--exclude-music", action="store_true")
    args = ap.parse_args()

    if args.inspect:
        inspect(args)
        return 0

    payload = build(args)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        f"wrote {out} — {payload['meta']['videoCount']:,} videos / "
        f"{payload['meta']['eventCount']:,} events / {payload['meta']['clusterCount']} clusters"
    )
    print(f"embedder={payload['meta']['embedder']} projection={payload['meta']['projection']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
