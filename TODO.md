# TODO – Fix data pulling issues

- [ ] Inspect current fetch + render flow (fetch_data.py writes `data.json`, index.html reads it)
- [ ] Add `debug` info into `data.json` from fetch_data.py (GA4 availability/skip reasons, CF7 endpoint/response status, hub_views)
- [ ] Update index.html to render debug block when `data.debug` exists (without breaking existing UI)
- [ ] Run `python scripts/fetch_data.py` locally (with missing secrets it will likely show skip reasons)
- [ ] Verify dashboard loads and shows debug info

