from pathlib import Path
import argparse
import json
import os
os.environ.setdefault('LOKY_MAX_CPU_COUNT', '1')
from .core import run_study

def main():
    parser=argparse.ArgumentParser(description='Publication-aware real public-data text/price study')
    parser.add_argument('--demo',action='store_true',help='Run the bundled real-data snapshot offline; no synthetic research results')
    parser.add_argument('--data',type=Path)
    parser.add_argument('--protocol',type=Path)
    parser.add_argument('--output',type=Path,default=Path('local-runs/study'))
    args=parser.parse_args()
    root=Path(__file__).parent
    data=args.data or root/'data'
    protocol=args.protocol or root/'protocol.json'
    result=run_study(data,protocol,args.output)
    print(json.dumps({k:result[k] for k in ['data_kind','eligible_events','partition_events','best_price_family','primary_contrast']},indent=2))

if __name__=='__main__':
    main()
