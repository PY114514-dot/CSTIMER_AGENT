"""
手动跑公式库 seed: 把 cubingapp/algdb 的 JSON 灌进 DB
用法:
    python -m scripts.import_formulas          # 拉所有 3x3 set
    python -m scripts.import_formulas PLL      # 只拉 PLL
    python -m scripts.import_formulas PLL OLL  # 多个
    python -m scripts.import_formulas --offline  # 只用 cache, 不联网
"""
from __future__ import annotations
import argparse
import os
import sys
import time

# 让脚本能 import app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.persistence.db import init_db
from app.persistence import db as _db
from app.persistence.formula_importer import import_all, import_one_set, DEFAULT_FILES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sets", nargs="*", help="set codes, e.g. PLL OLL F2L; default = all")
    ap.add_argument("--offline", action="store_true", help="use cache only, no network")
    args = ap.parse_args()

    print("=" * 60)
    print("Formula Library Seeder")
    print("=" * 60)
    init_db()

    if args.sets:
        targets = [f for f in DEFAULT_FILES if f[1] in args.sets]
        if not targets:
            print(f"  no matching sets for {args.sets}; choices: {[f[1] for f in DEFAULT_FILES]}")
            return 1
    else:
        targets = DEFAULT_FILES

    cache_dir = "data/formulas_cache"
    t0 = time.time()
    results = []
    with _db.SessionLocal() as s:
        for fn, code, name in targets:
            try:
                r = import_one_set(s, filename=fn, set_code=code, display_name=name,
                                    cache_dir=None if args.offline else cache_dir)
                print(f"  [OK] {code:6s} cases={r['case_count']:3d} algs={r['alg_count']:4d}")
                results.append(r)
            except Exception as e:
                print(f"  [ERR] {code:6s} {type(e).__name__}: {e}")
        s.commit()
    print(f"\nTotal: {len(results)} set(s), "
          f"{sum(r['case_count'] for r in results)} cases, "
          f"{sum(r['alg_count'] for r in results)} algs, "
          f"{time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
