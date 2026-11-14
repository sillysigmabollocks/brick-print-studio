"""Run a generation job with catalog files supplied by the web worker."""
import json
import shutil
from pathlib import Path

from .jobs import Studio


class BrowserStudio(Studio):
    def __init__(self, root, report):
        super().__init__(root, self.missing_file)
        self.report = report

    @staticmethod
    def missing_file(url, destination, status):
        raise RuntimeError(f'The browser catalog is missing {destination.name}.')

    def progress(self, job_id, message):
        self.store.update(job_id, message=message)
        self.report(message)


def generate(set_number, limit, calibration, report, *, group_by_color=True,
             include_minifigures=False, include_projectiles=True):
    studio = BrowserStudio(Path('/print-data'), report)
    job_id = studio.enqueue(set_number, dict(
        batches=True, max_per_plate=limit if group_by_color else None, calibration=calibration,
        group_by_color=group_by_color, include_minifigures=include_minifigures,
        include_projectiles=include_projectiles))
    try:
        studio.run(job_id)
        job = studio.snapshot(job_id)
        if job['state'] != 'complete':
            raise RuntimeError(job['message'])
        archive = studio.archive(job_id, job['metadata'])
        Path('/print-export.zip').write_bytes(archive.read_bytes())
        return json.dumps(dict(filename=archive.name, plates=job['plate_count'],
                               missing_figure_inventories=sum(
                                   item['quantity'] for item in job['metadata']['missing_minifigure_inventories']),
                               **job['quantity_summary']))
    finally:
        shutil.rmtree(studio.root / 'output' / job_id, ignore_errors=True)
