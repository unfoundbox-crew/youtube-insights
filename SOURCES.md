# Takeout format notes

The importer is intentionally defensive because Google Takeout exports vary over time, locale, selected products, and account history.

References checked while building this package:

- Google Takeout documentation / export schema: https://github.com/google/takeout
- Google Account Help — download your Google data: https://support.google.com/accounts/answer/3024190
- `google_takeout_parser`, a long-running parser supporting current JSON and legacy HTML YouTube history: https://github.com/purarue/google_takeout_parser
- Current `watch-history.json` field guide (August 2026): https://smallwebapps.com/guides/youtube-watch-history-json-format/

Common current path:

```text
Takeout/YouTube and YouTube Music/history/watch-history.json
```

Legacy exports can instead contain:

```text
Takeout/YouTube and YouTube Music/history/watch-history.html
```

Older / additional activity may also occur under a YouTube `My Activity` export. The parser scans ZIPs and extracted directories rather than requiring one hard-coded root path.
