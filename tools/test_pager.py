# -*- coding: utf-8 -*-
"""Test online search pagination on iStoreOS dlna-speaker."""
import json
import urllib.parse
import urllib.request

BASE = "http://192.168.1.10:5000/api/online/search"
q = urllib.parse.quote("孤勇者")
prov = urllib.parse.quote("元力WY")

for page in (1, 2, 3, 4):
    url = f"{BASE}?q={q}&provider={prov}&page={page}&limit=10"
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"page {page}: ERROR {e}")
        continue
    its = d.get("items", [])
    first = its[0]["title"][:16] if its else "-"
    last = its[-1]["title"][:16] if its else "-"
    print(f"page {page}: count={len(its)} isEnd={d.get('isEnd')} first=[{first}] last=[{last}]")
