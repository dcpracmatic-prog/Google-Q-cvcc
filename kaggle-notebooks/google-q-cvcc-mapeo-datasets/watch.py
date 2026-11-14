#!/usr/bin/env python3
"""Vigila el kernel de validación hasta que termine y baja su salida.
Uso: watch.py  (imprime el estado en cada chequeo; al terminar descarga
el zip a ./kaggle-out.zip y lista los archivos + el RESUMEN_KAGGLE)."""
import json, subprocess, sys, time, zipfile
from pathlib import Path
sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry, ensure_allowed_url

HERE = Path(__file__).resolve().parent
SLUG = "google-q-cvcc-mapeo-de-datasets-y-llm-en-cpu"
USER = "dcpracmatic"

def api_get(path):
    url = "https://www.kaggle.com" + path
    ensure_allowed_url(url, ["www.kaggle.com"])
    s = str(dynamic_credential_entry("custom.kaggle", "access_token")["surrogate"]).strip()
    r = subprocess.run(["curl", "-s", "-m", "60", "-H", f"Authorization: Bearer {s}",
                        "-H", "Accept: application/json", url],
                       capture_output=True, text=True, timeout=70)
    return r.stdout

for i in range(30):
    raw = api_get(f"/api/v1/kernels/status?userName={USER}&kernelSlug={SLUG}")
    try:
        d = json.loads(raw)
    except Exception:
        print(f"[{i}] sin JSON: {raw[:200]}", flush=True)
        time.sleep(120); continue
    st = (d.get("status") or "").lower()
    print(f"[{i}] status={st} failure={d.get('failureMessage','')[:200]}", flush=True)
    if st in ("complete", "error", "cancelled"):
        break
    time.sleep(120)
else:
    print("TIMEOUT 60 min sin terminar", flush=True)
    sys.exit(2)

print("STATUS FINAL:", st, flush=True)
if st == "complete":
    dest = HERE / "kaggle-out.zip"
    r = subprocess.run(["python3", str(Path.home() / "workspace/custom-connectors/custom.kaggle/bin/kaggle_download.py"),
                        USER, SLUG, str(dest)], capture_output=True, text=True, timeout=180)
    print(r.stdout, r.stderr, flush=True)
    if dest.exists():
        zf = zipfile.ZipFile(dest)
        print("ARCHIVOS DE SALIDA:", zf.namelist(), flush=True)
        outdir = HERE / "kaggle-out"
        zf.extractall(outdir)
        for name in zf.namelist():
            txt = (outdir / name).read_text(errors="replace") if name.endswith((".log", ".json", ".txt")) else ""
            if "RESUMEN_KAGGLE" in txt or "VEREDICTO" in txt or name.endswith("VEREDICTO.json"):
                print(f"===== {name} =====", flush=True)
                print(txt[-6000:], flush=True)
