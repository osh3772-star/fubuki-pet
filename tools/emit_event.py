"""Send a state to the optional local file inbox; never modifies hook settings."""
from pathlib import Path
import argparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from windows_pet.events import emit
from windows_pet.core import JOB_STATES
if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state',choices=sorted(JOB_STATES))
    parser.add_argument('--session',default='manual')
    args=parser.parse_args()
    emit(args.state,'manual',args.session)
    print('State queued. Enable local event reception in the Fubuki menu.')
