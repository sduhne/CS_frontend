#!/usr/bin/env python3
"""Compute the share of trading days in the last year where TSLA had a
"-2% or more" intraday move.

Three definitions are reported. The primary metric (B) is the intraday
drawdown: the day's LOW was 2% or more below the day's OPEN, i.e. at some
point during the session the price traded at least 2% under the open.

Usage
-----
Fetch live (needs internet + `pip install yfinance pandas`):
    python tsla_intraday_movement.py

Offline, from a CSV with columns Date,Open,High,Low,Close (header required):
    python tsla_intraday_movement.py --csv tsla.csv

Options
-------
    --threshold -2.0   percent threshold (default -2.0)
    --period 1y        yfinance period when fetching live (default 1y)
"""
import argparse
import sys


def load_from_csv(path):
    import csv
    rows = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        # normalise header capitalisation
        field_map = {k.lower(): k for k in reader.fieldnames or []}
        for need in ("open", "high", "low", "close"):
            if need not in field_map:
                sys.exit(f"CSV missing required column: {need}")
        for r in reader:
            try:
                rows.append({
                    "date": r.get(field_map.get("date", "Date"), ""),
                    "open": float(r[field_map["open"]]),
                    "high": float(r[field_map["high"]]),
                    "low": float(r[field_map["low"]]),
                    "close": float(r[field_map["close"]]),
                })
            except (ValueError, KeyError):
                continue  # skip blank/partial rows
    return rows


def load_live(period):
    try:
        import yfinance as yf
    except ImportError:
        sys.exit("yfinance not installed. Run: pip install yfinance pandas\n"
                 "Or use --csv to analyze a local file.")
    df = yf.download("TSLA", period=period, interval="1d",
                     auto_adjust=False, progress=False)
    if df.empty:
        sys.exit("No data returned from yfinance (network blocked?). "
                 "Try --csv with a downloaded file.")
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    rows = []
    for idx, r in df.iterrows():
        rows.append({
            "date": str(idx.date()),
            "open": float(r["Open"]),
            "high": float(r["High"]),
            "low": float(r["Low"]),
            "close": float(r["Close"]),
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="path to OHLC csv (offline mode)")
    ap.add_argument("--threshold", type=float, default=-2.0,
                    help="percent threshold, default -2.0")
    ap.add_argument("--period", default="1y", help="yfinance period, default 1y")
    args = ap.parse_args()

    rows = load_from_csv(args.csv) if args.csv else load_live(args.period)
    n = len(rows)
    if n == 0:
        sys.exit("No usable rows.")

    thr = args.threshold
    a = b = c = 0
    prev_close = None
    for r in rows:
        oc = (r["close"] - r["open"]) / r["open"] * 100          # open -> close
        lo = (r["low"] - r["open"]) / r["open"] * 100            # intraday low vs open
        a += oc <= thr
        b += lo <= thr
        if prev_close is not None:
            pc = (r["low"] - prev_close) / prev_close * 100      # low vs prev close
            c += pc <= thr
        prev_close = r["close"]

    print(f"TSLA — trading days analyzed: {n}")
    print(f"  Range: {rows[0]['date']} .. {rows[-1]['date']}")
    print(f"  Threshold: {thr:.1f}%\n")
    print(f"A) Open->Close <= {thr:.0f}%:            {a:3d} days = {a/n*100:5.1f}%")
    print(f"B) Intraday low <= {thr:.0f}% of open:   {b:3d} days = {b/n*100:5.1f}%   <- primary")
    print(f"C) Low <= {thr:.0f}% of prev close:      {c:3d} days = {c/n*100:5.1f}%")


if __name__ == "__main__":
    main()
