#!/usr/bin/env python3
"""Sube un notebook Kaggle (privado) con POST /api/v1/kernels/push.

Nombres de campo exactos (del SDK oficial kagglesdk, ApiSaveKernelRequest,
leído de kaggle/api/kaggle_api_extended.py::kernels_push):
  slug (ref completo "dueño/slug"), newTitle (NO 'title'), text (el .ipynb
  en texto plano, NO base64), language, kernelType, isPrivate, enableGpu,
  enableTpu, enableInternet, datasetDataSources, competitionDataSources.
La API v1 es gRPC-JSON: los campos van en camelCase.

Uso: python3 push_notebook.py <dir-del-notebook>
El dir debe tener vqcc-auto-optimizer-30.ipynb y kernel-metadata.json.
Usa el Bearer surrogate de custom.kaggle (igual que kaggle.py).
Imprime la respuesta JSON de Kaggle (con el ref del kernel).
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry, ensure_allowed_url

URL = "https://www.kaggle.com/api/v1/kernels/push"


def main() -> int:
    d = Path(sys.argv[1])
    meta = json.loads((d / "kernel-metadata.json").read_text())
    nb_text = (d / meta["code_file"]).read_text(encoding="utf-8")
    payload = {
        "id": meta.get("id_no", 0),
        "slug": meta["id"],
        "newTitle": meta["title"],
        "text": nb_text,
        "language": meta["language"],
        "kernelType": meta["kernel_type"],
        "isPrivate": meta["is_private"],
        "enableGpu": meta["enable_gpu"],
        "enableTpu": meta["enable_tpu"],
        "enableInternet": meta["enable_internet"],
        "datasetDataSources": meta.get("dataset_sources", []),
        "competitionDataSources": meta.get("competition_sources", []),
        "kernelDataSources": meta.get("kernel_sources", []),
        "modelDataSources": meta.get("model_sources", []),
        "categoryIds": meta.get("keywords", []),
    }
    ensure_allowed_url(URL, ["www.kaggle.com"])
    entry = dynamic_credential_entry("custom.kaggle", "access_token")
    surrogate = str(entry["surrogate"]).strip()
    # El payload (con el notebook en texto) es grande: se escribe a un
    # archivo y se pasa con -d @archivo, no como argumento (ARG_MAX).
    payload_path = Path("/tmp/kaggle_kernel_push.json")
    payload_path.write_text(json.dumps(payload))
    result = subprocess.run(
        ["curl", "-s", "-m", "90", "-X", "POST",
         "-H", f"Authorization: Bearer {surrogate}",
         "-H", "Content-Type: application/json",
         "-H", "Accept: application/json",
         "-d", f"@{payload_path}", URL],
        capture_output=True, text=True, timeout=100,
    )
    print(result.stdout[:8000])
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
