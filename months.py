#!/usr/bin/env python3
import argparse
from sys import argv
from datetime import datetime, timedelta
from datetime import date
from dateutil.relativedelta import relativedelta


def fmt(dt):
    return dt.strftime('%Y-%m-%d')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('start_at', action='store', help='start month')
    parser.add_argument('--cmd', action='store', default='', help="cmd")
    parser.add_argument('--start-prefix', action='store', default='--start-at=', help="start prefix")
    parser.add_argument('--end-prefix', action='store', default='--end-at=', help="end prefix")
    parser.add_argument('--extra-fmt', action='store', default=None, help="extra fmt for start month")

    args = parser.parse_args()
    start_at = datetime.strptime(args.start_at, '%Y-%m').date()
    start_at.replace(day=1)
    end_at = (date.today() + relativedelta(months=+1)) .replace(day=1)
    cur_start = start_at
    while cur_start < end_at:
        cur_end = cur_start + relativedelta(months=+1)
        extra = ''
        if args.extra_fmt:
            extra = args.extra_fmt % cur_start.strftime('%Y-%m')
        print(f'{args.cmd} {args.start_prefix}{fmt(cur_start)} {args.end_prefix}{fmt(cur_end)} {extra}')
        cur_start = cur_end

if __name__ == '__main__':
    main()
