"""Run one print job without starting the local web server."""
import argparse
import json
from pathlib import Path
import shutil

from .jobs import Studio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('set_number')
    parser.add_argument('--data', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, default=Path('exports'))
    parser.add_argument('--max-per-plate', type=int, choices=range(1, 101), default=30,
                        metavar='1–100')
    parser.add_argument('--calibration', action='store_true')
    args = parser.parse_args()
    studio = Studio(args.data)
    try:
        job_id = studio.enqueue(args.set_number, dict(
            batches=True, max_per_plate=args.max_per_plate, calibration=args.calibration))
    except ValueError as error:
        parser.error(str(error))
    studio.run(job_id)
    job = studio.snapshot(job_id)
    if job['state'] != 'complete':
        parser.exit(1, f"Export failed: {job['message']}\n")
    archive = studio.archive(job_id, job['metadata'])
    args.output.mkdir(parents=True, exist_ok=True)
    exported = args.output / archive.name
    shutil.copyfile(archive, exported)
    counts = job['quantity_summary']
    print(json.dumps(dict(
        file=str(exported), plates=job['plate_count'], **counts)), flush=True)


if __name__ == '__main__':
    main()
