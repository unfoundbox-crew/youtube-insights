# Unfoundbox Galaxy

Local-first semantic map of your YouTube history.

Drop a Google Takeout ZIP into the pipeline, build a semantic 3D map locally, and explore it in your browser. Your watch history does not need to leave your machine.

## What it supports

- Google Takeout `.zip`, extracted Takeout directory, `watch-history.json`, or legacy `watch-history.html`
- Current JSON entries such as `title`, `titleUrl`, `subtitles`, `time`, `details`, and `activityControls`
- Aggregation of repeat watches into one video point with watch count / first seen / last seen
- Local embeddings with Sentence Transformers when available
- Zero-model fallback using TF-IDF + SVD
- 3D projection using UMAP when installed; PCA fallback otherwise
- Automatic topic clusters
- Search, timeline filtering, cluster filtering, point inspection, related-video links, and a time playback mode
- Fully local web UI after dependencies are installed

## 1. Export from Google Takeout

In Google Takeout:

1. Deselect all.
2. Select **YouTube and YouTube Music**.
3. Under **Multiple formats**, choose **JSON** for history if Google offers the option.
4. Under **All YouTube data included**, keep **history**. You may leave playlists/subscriptions too; this importer simply ignores unsupported files.
5. Create a ZIP export.

Typical current path inside the ZIP:

```text
Takeout/
└── YouTube and YouTube Music/
    └── history/
        └── watch-history.json
```

Older Takeouts may contain `watch-history.html`; the importer supports that too.

## 2. One-command setup

Requires Python 3.10+. The viewer itself has no npm/Node dependencies.

```bash
cd unfoundbox-galaxy
./setup.sh
```

For the stronger local embedding backend, either run `./setup.sh --semantic` initially or later run `./galaxy semantic-setup`.

## 3. Build your galaxy

```bash
./galaxy build ~/Downloads/takeout-*.zip
```

This writes:

```text
app/data/galaxy.json
```

Then run:

```bash
./galaxy dev
```

Open the localhost URL printed by Vite.

## Useful build options

Fastest / no model download:

```bash
./galaxy build ~/Downloads/takeout.zip --embedder tfidf
```

Better semantic map using a local embedding model (after `./galaxy semantic-setup`):

```bash
./galaxy build ~/Downloads/takeout.zip --embedder sentence-transformers
```

Use a different model:

```bash
./galaxy build ~/Downloads/takeout.zip \
  --embedder sentence-transformers \
  --model sentence-transformers/all-MiniLM-L6-v2
```

Limit while experimenting:

```bash
./galaxy build ~/Downloads/takeout.zip --limit 5000
```

Exclude YouTube Music-like entries heuristically:

```bash
./galaxy build ~/Downloads/takeout.zip --exclude-music
```

## Commands

```text
./galaxy build <takeout>    parse + aggregate + embed + project + cluster
./galaxy dev                run the interactive local app
./galaxy demo               regenerate bundled synthetic demo data
./galaxy inspect <takeout>  print detected history files and parsed counts
```

## Privacy

The pipeline reads local files and writes a local JSON artifact. The web app reads that static artifact from localhost. There is no analytics code and no application backend.

If you use `sentence-transformers`, the selected model weights are downloaded from the model host the first time unless already cached. After that, inference is local. Use `--embedder tfidf` for a no-model-download path.

## Design notes

The visualization intentionally treats one unique video as one persistent point. Repeat watches increase point size rather than creating overlapping duplicate points. This makes spatial memory possible while preserving revisit behavior.

The generated JSON also stores timestamps for every watch of each video, so an event-level visualization can be added later without reparsing Takeout.

## Next upgrades

The data schema is designed to accept other source types later: X bookmarks, GitHub repos/issues/commits, papers, chats, webpages, notes, and project anchors. The `source` and `kind` fields already exist for that reason.
