"""Probe image-backed rare-text correction without running ASR or authoring a guide."""
import argparse,json
from pathlib import Path
from auto_guide import Pipeline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,help='Existing pipeline output containing keyframes and screen_text')
    parser.add_argument('--output',required=True,help='Separate directory for probe traces and decisions')
    parser.add_argument('--read',action='append',help='Only probe this OCR reading; repeat for multiple readings')
    parser.add_argument('--model',default='qwen38')
    parser.add_argument('--base',default='http://127.0.0.1:8000/v1')
    parser.add_argument('--api-parallel',type=int,default=1)
    parser.set_defaults(parallel=1)
    args=parser.parse_args()
    if args.api_parallel<1:parser.error('--api-parallel must be positive')
    source=Path(args.source).resolve();out=Path(args.output).resolve()
    if out==source:parser.error('Use a separate output directory; filtered probes must not replace full pipeline decisions')
    out.mkdir(parents=True,exist_ok=True);(out/'traces').mkdir(exist_ok=True)
    if not (out/'frames').exists():(out/'frames').symlink_to(source/'frames',target_is_directory=True)
    p=Pipeline.__new__(Pipeline);p.init_transport(args);p.out=out;p.args=args;p.headers={'Content-Type':'application/json'}
    import os
    if os.environ.get('VIDEO_GUIDE_API_KEY'):p.headers['Authorization']='Bearer '+os.environ['VIDEO_GUIDE_API_KEY']
    p.frames=json.loads((source/'keyframes.json').read_text());p.screen=json.loads((source/'screen_text.json').read_text())
    p.recheck_rare_text(set(args.read) if args.read else None)
    for c in json.loads((out/'screen_rechecks.json').read_text()):print(c['accepted'],c['p'],c['read'],'->',c['candidate'])

if __name__=='__main__':main()
