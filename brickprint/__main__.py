import argparse
import threading
import webbrowser

import uvicorn


def main():
    parser = argparse.ArgumentParser(description='Run Brick Print Studio locally.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    print(f'Brick Print Studio · {url}', flush=True)
    if not args.no_browser:
        launch = threading.Timer(1.5, webbrowser.open, args=[url])
        launch.daemon = True
        launch.start()
    uvicorn.run('brickprint.app:app', host='127.0.0.1', port=args.port, workers=1)


if __name__ == '__main__':
    main()
