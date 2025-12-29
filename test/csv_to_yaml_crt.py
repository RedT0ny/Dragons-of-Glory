#!/usr/bin/env python3
"""Convert a CRT CSV into YAML.

Supports TWO input CSV layouts:

(A) "Slash" layout (common CRT export)
    Columns: Roll, 1:3, 1:2, ...
    Cell values: attacker/defender
      Examples: E/-, DR/2, D/2R, -/DR

(B) "Split" layout (already separated + retreat flags)
    Columns: ModifiedD10Roll and, for each odds column (e.g., 1-3):
      1-3_AttackerResult, 1-3_AttackerRetreat, 1-3_DefenderResult, 1-3_DefenderRetreat

Output YAML schema:
  table_name
  notes
  columns: [odds...]
  rows:
    "-5":
      "1-3":
        attacker: {result: "E", retreat: false}
        defender: {result: "", retreat: false}
  legend (optional)

Usage:
  python csv_to_yaml_crt.py input.csv output.yaml
"""

import re
import sys
import pandas as pd
import yaml


def _normalize_blank(x: str) -> str:
    x = ('' if x is None else str(x)).strip()
    return '' if x == '-' or x.lower() == 'nan' else x


def _parse_side(code: str):
    """Return (result, retreat_bool) from codes like '', '1', '2', '1R', '2R', 'D', 'D1', 'E', 'DR'."""
    code = _normalize_blank(code)
    if code == '':
        return '', False

    retreat = False
    base = code

    # e.g., 1R, 2R
    if base.endswith('R'):
        retreat = True
        base = base[:-1]

    # DR means D + retreat
    if base == 'DR':
        retreat = True
        base = 'D'

    return base, retreat


def _detect_layout(columns):
    cols = set(columns)
    if 'Roll' not in cols:
        raise ValueError("CSV must include a 'Roll' column")

    # Split layout detection: any *_AttackerResult columns
    if any(c.endswith('_AttackerResult') for c in cols):
        return 'split'

    # Slash layout: any odds-style header like '1-3' etc.
    odds_pat = re.compile(r'^\d-\d$')
    if any(odds_pat.match(c) for c in cols if c != 'Roll'):
        return 'slash'

    raise ValueError('Unrecognized CSV layout. Expected slash-layout odds columns (e.g., 1-3) or split-layout columns (e.g., 1-3_AttackerResult).')


def csv_to_yaml(csv_path: str, include_legend: bool = True) -> dict:
    df = pd.read_csv(csv_path, dtype=str).fillna('')
    layout = _detect_layout(df.columns)

    crt = {
        'table_name': 'Combat Results Table',
        'notes': 'Results to the left of the slash apply to the attacker; results to the right apply to the defender.',
        'columns': [],
        'rows': {},
    }

    if include_legend:
        crt['legend'] = {
            '1': 'The force suffers one depletion',
            '2': 'The force suffers two depletions',
            'D': 'Every unit in the force suffers one depletion',
            'R': 'All units must retreat one hex',
            'E': 'All units are eliminated',
        }

    if layout == 'slash':
        odds_cols = [c for c in df.columns if c != 'ModifiedD10Roll']
        crt['columns'] = odds_cols

        for _, r in df.iterrows():
            roll = str(r['ModifiedD10Roll']).strip()
            crt['rows'][roll] = {}
            for o in odds_cols:
                cell = str(r[o]).strip()
                if '/' not in cell:
                    raise ValueError(f"Cell '{cell}' at roll={roll}, odds={o} is missing '/'")
                left, right = cell.split('/', 1)
                a_res, a_ret = _parse_side(left)
                d_res, d_ret = _parse_side(right)
                crt['rows'][roll][o] = {
                    'attacker': {'result': a_res, 'retreat': a_ret},
                    'defender': {'result': d_res, 'retreat': d_ret},
                }

    else:  # split
        # Determine odds by scanning *_AttackerResult columns
        odds = []
        for c in df.columns:
            if c.endswith('_AttackerResult'):
                odds.append(c[:-len('_AttackerResult')])
        # Preserve a sensible common order if possible
        preferred = ['1:3','1:2','2:3','1:1','3:2','2:1','3:1','4:1','5:1','6:1']
        odds = [o for o in preferred if o in odds] + [o for o in odds if o not in preferred]
        crt['columns'] = odds

        def as_bool(x):
            return str(x).strip().upper() == 'TRUE'

        for _, r in df.iterrows():
            roll = str(r['ModifiedD10Roll']).strip()
            crt['rows'][roll] = {}
            for o in odds:
                a_res = _normalize_blank(r.get(f'{o}_AttackerResult',''))
                a_ret = as_bool(r.get(f'{o}_AttackerRetreat','FALSE'))
                d_res = _normalize_blank(r.get(f'{o}_DefenderResult',''))
                d_ret = as_bool(r.get(f'{o}_DefenderRetreat','FALSE'))
                crt['rows'][roll][o] = {
                    'attacker': {'result': a_res, 'retreat': a_ret},
                    'defender': {'result': d_res, 'retreat': d_ret},
                }

    return crt


def main(argv):
    if len(argv) != 3:
        print('Usage: python csv_to_yaml_crt.py input.csv output.yaml', file=sys.stderr)
        return 2

    in_csv, out_yaml = argv[1], argv[2]
    data = csv_to_yaml(in_csv)
    with open(out_yaml, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
