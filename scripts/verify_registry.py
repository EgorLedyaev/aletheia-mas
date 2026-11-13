
"""Verify availability + versions of every tool/DB Aletheia calls, and emit registry/tools.yaml.

Run:  python scripts/verify_registry.py
Writes: registry/tools.yaml, registry/verification_log.json
Licence strings are transcribed from each project's own published terms; `license_source`
records where the string came from. Anything not confirmable programmatically is emitted
with status UNVERIFIED rather than assumed.
"""
import json, hashlib, importlib, platform, subprocess, datetime, os
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

PY_LIBS = [
    ("rdkit", "BSD-3-Clause", "https://github.com/rdkit/rdkit/blob/master/license.txt"),
    ("sklearn", "BSD-3-Clause", "https://github.com/scikit-learn/scikit-learn/blob/main/COPYING"),
    ("pydantic", "MIT", "https://github.com/pydantic/pydantic/blob/main/LICENSE"),
    ("numpy", "BSD-3-Clause", "https://numpy.org/doc/stable/license.html"),
    ("pandas", "BSD-3-Clause", "https://github.com/pandas-dev/pandas/blob/main/LICENSE"),
    ("scipy", "BSD-3-Clause", "https://github.com/scipy/scipy/blob/main/LICENSE.txt"),
    ("matplotlib", "matplotlib (PSF-based)", "https://matplotlib.org/stable/project/license.html"),
    ("Bio", "Biopython License / BSD-3-Clause", "https://github.com/biopython/biopython/blob/master/LICENSE.rst"),
]

ENDPOINTS = [
    ("ChEMBL", "https://www.ebi.ac.uk/chembl/api/data/status.json",
     "CC BY-SA 3.0", "https://chembl.gitbook.io/chembl-interface-documentation/about"),
    ("PubChem PUG-REST", "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/2244/property/MolecularFormula/JSON",
     "Public domain (NCBI); depositor terms vary", "https://www.ncbi.nlm.nih.gov/home/about/policies/"),
    ("UniProtKB REST", "https://rest.uniprot.org/uniprotkb/P00533.json?fields=accession",
     "CC BY 4.0", "https://www.uniprot.org/help/license"),
    ("RCSB PDB Data API", "https://data.rcsb.org/rest/v1/core/entry/1M17",
     "CC0 1.0 (PDB core data)", "https://www.rcsb.org/pages/usage-policy"),
    ("AlphaFold DB", "https://alphafold.ebi.ac.uk/api/prediction/P00533",
     "CC BY 4.0", "https://alphafold.ebi.ac.uk/faq"),
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    log, entries = [], []
    entries.append({"name": "python", "kind": "runtime", "version": platform.python_version(),
                    "platform": platform.platform(), "license": "PSF-2.0",
                    "license_source": "https://docs.python.org/3/license.html",
                    "status": "VERIFIED", "verified_at": NOW})
    for mod, lic, lic_src in PY_LIBS:
        try:
            m = importlib.import_module(mod)
            v = str(getattr(m, "__version__", getattr(m, "VERSION", "unknown")))
            entries.append({"name": mod, "kind": "python-library", "version": v, "license": lic,
                            "license_source": lic_src, "status": "VERIFIED", "verified_at": NOW})
            log.append({"check": "import " + mod, "result": "ok", "version": v})
        except Exception as exc:
            entries.append({"name": mod, "kind": "python-library", "version": None, "license": lic,
                            "license_source": lic_src, "status": "UNVERIFIED",
                            "error": str(exc)[:200], "verified_at": NOW})
            log.append({"check": "import " + mod, "result": "fail", "error": str(exc)[:200]})

    vina = os.path.join(HERE, "tools", "vina", "vina_1.2.7_win.exe")
    if os.path.exists(vina):
        out = subprocess.run([vina, "--version"], capture_output=True, text=True).stdout.strip()
        entries.append({"name": "AutoDock Vina", "kind": "binary",
                        "version": out.splitlines()[0] if out else None,
                        "path": os.path.relpath(vina, HERE), "sha256": sha256(vina),
                        "license": "Apache-2.0",
                        "license_source": "https://github.com/ccsb-scripps/AutoDock-Vina/blob/develop/LICENSE",
                        "source_url": "https://github.com/ccsb-scripps/AutoDock-Vina/releases/tag/v1.2.7",
                        "status": "VERIFIED", "verified_at": NOW})
        log.append({"check": "vina --version", "result": "ok", "stdout": out[:120]})
    else:
        entries.append({"name": "AutoDock Vina", "kind": "binary", "status": "UNVERIFIED",
                        "error": "binary absent; run make setup", "verified_at": NOW})

    try:
        ob = subprocess.run(["obabel", "-V"], capture_output=True, text=True)
        entries.append({"name": "Open Babel", "kind": "binary",
                        "version": (ob.stdout or ob.stderr).strip()[:60], "license": "GPL-2.0",
                        "license_source": "https://github.com/openbabel/openbabel/blob/master/COPYING",
                        "status": "VERIFIED" if ob.returncode == 0 else "UNVERIFIED",
                        "verified_at": NOW})
        log.append({"check": "obabel -V", "result": ob.returncode})
    except Exception as exc:
        entries.append({"name": "Open Babel", "kind": "binary", "status": "UNVERIFIED",
                        "error": str(exc)[:200], "verified_at": NOW})

    for name, url, lic, lic_src in ENDPOINTS:
        rec = {"name": name, "kind": "database-api", "endpoint": url.split("?")[0],
               "license": lic, "license_source": lic_src, "verified_at": NOW}
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                body = r.read(2000)
                rec["http_status"] = r.status
                rec["status"] = "VERIFIED" if r.status == 200 else "UNVERIFIED"
                rec["response_sha256_prefix"] = hashlib.sha256(body).hexdigest()[:16]
            log.append({"check": url, "result": rec["http_status"]})
        except Exception as exc:
            rec["status"] = "UNVERIFIED"
            rec["error"] = str(exc)[:200]
            log.append({"check": url, "result": "fail", "error": str(exc)[:200]})
        entries.append(rec)

    os.makedirs(os.path.join(HERE, "registry"), exist_ok=True)
    try:
        import yaml
        text = yaml.safe_dump({"generated_at": NOW, "entries": entries}, sort_keys=False,
                              allow_unicode=True)
    except ImportError:
        text = json.dumps({"generated_at": NOW, "entries": entries}, indent=2)
    with open(os.path.join(HERE, "registry", "tools.yaml"), "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(os.path.join(HERE, "registry", "verification_log.json"), "w", encoding="utf-8") as fh:
        json.dump({"generated_at": NOW, "checks": log}, fh, indent=2)
    n_ok = sum(1 for e in entries if e.get("status") == "VERIFIED")
    print("registry: %d/%d VERIFIED" % (n_ok, len(entries)))
    for e in entries:
        if e.get("status") != "VERIFIED":
            print("  UNVERIFIED:", e["name"], str(e.get("error", ""))[:90])


if __name__ == "__main__":
    main()
