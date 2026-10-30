"""Explicit local MP4 demonstration, independent of observation/AI data."""
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

from flask import jsonify, request, send_file
from .instance import safe_path

URL = '/media/local-demo.mp4'


@dataclass(frozen=True)
class LocalDemoVideo:
    path: Path
    identity: tuple

    @classmethod
    def open(cls, path):
        path = Path(path).absolute()
        try:
            safe_path(path)
            if not path.is_file() or path.suffix.lower() != '.mp4': raise ValueError()
            with path.open('rb') as stream:
                if stream.read(12)[4:8] != b'ftyp': raise ValueError()
            stat = path.stat()
            return cls(path, (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns))
        except (OSError, ValueError):
            raise ValueError('LOCAL_DEMO_MP4_REQUIRED') from None

    def metadata(self):
        return dict(kind='local_file', url=URL, label='本地演示视频（非实时设备）')

    def unchanged(self):
        try:
            safe_path(self.path)
            stat = self.path.stat()
            return self.identity == (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        except (OSError, ValueError):
            return False


def register_demo_video(app, video):
    if type(video) is not LocalDemoVideo: raise ValueError('INVALID_LOCAL_DEMO_VIDEO')

    @app.get(URL)
    def local_demo_video():
        try:
            local = ip_address(request.remote_addr or '').is_loopback
        except ValueError:
            local = False
        if not local: return jsonify(error_code='LOCAL_VIDEO_ACCESS_DENIED'),403
        if not video.unchanged(): return jsonify(error_code='LOCAL_VIDEO_CHANGED_RESTART_REQUIRED'),409
        return send_file(video.path, mimetype='video/mp4', conditional=True,
                         as_attachment=False, download_name='local-demo.mp4')
