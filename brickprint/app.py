"""Loopback-only web API."""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .jobs import Studio

WEB = Path(__file__).with_name('web')


class JobRequest(BaseModel):
    set_number: str = Field(min_length=1, max_length=26)
    batches: bool = True
    max_per_plate: int = Field(default=30, ge=1, le=100)
    calibration: bool = False


def create_app(studio=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.studio = studio or Studio(Path(os.environ.get(
            'BRICKPRINT_DATA_DIR', str(Path(__file__).resolve().parents[1] / 'data'))))
        app.state.studio.start()
        try:
            yield
        finally:
            app.state.studio.close()

    app = FastAPI(title='Brick Print Studio', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])
    app.mount('/static', StaticFiles(directory=WEB), name='static')

    @app.middleware('http')
    async def local_requests(request: Request, call_next):
        if request.method == 'POST':
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': 'Open Brick Print Studio on this computer.'}, 403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/')
    def home():
        return FileResponse(WEB / 'index.html', headers={'Cache-Control': 'no-cache'})

    @app.get('/api/profile')
    def profile(request: Request):
        return request.app.state.studio.profile

    @app.get('/api/jobs')
    def jobs(request: Request):
        return request.app.state.studio.store.list()

    @app.post('/api/jobs', status_code=202)
    def generate(payload: JobRequest, request: Request):
        options = payload.model_dump(exclude={'set_number'})
        try:
            return {'id': request.app.state.studio.enqueue(payload.set_number, options)}
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.get('/api/jobs/{job_id}')
    def progress(job_id: str, request: Request):
        job = request.app.state.studio.snapshot(job_id)
        if job is None:
            raise HTTPException(404, 'Job not found.')
        return JSONResponse(job, headers={'Cache-Control': 'no-store'})

    @app.post('/api/jobs/{job_id}/resume', status_code=202)
    def resume(job_id: str, request: Request):
        studio = request.app.state.studio
        if not studio.store.resume(job_id):
            raise HTTPException(409, 'Only failed jobs can be resumed manually.')
        studio.wake.set()
        return {'id': job_id}

    @app.get('/api/jobs/{job_id}/download')
    def download(job_id: str, request: Request):
        studio = request.app.state.studio
        job = studio.store.get(job_id)
        if not job or job['state'] != 'complete':
            raise HTTPException(404, 'The ZIP is still being prepared or this job is unavailable.')
        path = studio.archive(job_id, job['metadata'])
        if not path.is_file():
            raise HTTPException(404, 'The ZIP is missing from the output folder.')
        return FileResponse(path, filename=path.name, media_type='application/zip')

    return app


app = create_app()
