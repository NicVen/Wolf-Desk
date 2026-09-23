# Public track record — PC → VPS proof wall

The public page at **https://staalwag.com/proof** shows STAALWAG's honest,
append-only record. It never re-scores anything: the PC HQ forwards the exact
numbers it already banked, so the public wall can never disagree with your
private cockpit. Losses are sent too — that's the point.

```
  PC HQ (refresh.ps1)                          VPS (serve.py, :8777)
  -------------------                          ---------------------
  desk_bank.py   -> desk_bank_view.json  \
  paperclip_*.py -> paperclip_view.json   >  push_proof.py --POST /proof-->  data/proof.json
                                         /     (WOLF_PASS key)                  |
                                                                    GET /proof      (public page)
                                                                    GET /proof.json (data)
```

The VPS side is already live (`POST /proof` key-gated ingest, `GET /proof`
page, `GET /proof.json`). Nothing to configure there beyond a normal deploy.

## One-time setup on the PC

1. Copy the publisher into the HQ folder (so it sits next to the view files):

   ```powershell
   copy "<wolf-desk repo>\deploy\push_proof.py" `
        "C:\Users\nvent\OneDrive\Desktop\CLAUDE\Projects\STAALWAG-HQ\push_proof.py"
   ```

2. Store the admin key once as a machine env var (same key the WOLF desk uses).
   It is read from the environment — **never** hard-code it in a script:

   ```powershell
   setx WOLF_PASS "your-real-admin-key"
   ```

   (Open a fresh PowerShell after `setx` so the variable is visible.)

## Publish after every refresh (automatic)

Add this one line to the **end** of `refresh.ps1`, just before the
`refresh done` marker — it runs right after `desk_bank.py` has rebuilt
`desk_bank_view.json`:

```powershell
# Public track record: forward the banked numbers to the VPS proof wall.
& $py (Join-Path $hq "push_proof.py") 2>&1 | Where-Object { $_ -notmatch "platform independent" } | Add-Content $log
```

Now every daily refresh (open HQ before London) updates the public record.

## Run it by hand / check it first

```powershell
cd "C:\Users\nvent\OneDrive\Desktop\CLAUDE\Projects\STAALWAG-HQ"
python push_proof.py --dry   # print the exact snapshot, send nothing
python push_proof.py         # publish -> https://staalwag.com/proof
```

Defaults: `HQ_DIR` = the folder `push_proof.py` lives in; `WOLF_HOST` =
`https://staalwag.com`. Override with env vars (e.g. `WOLF_HOST` =
`https://178.104.88.38.sslip.io`) if the domain is ever down.
