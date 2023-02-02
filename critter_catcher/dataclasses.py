from dataclasses import dataclass
import datetime


@dataclass
class Config:
    host: str
    port: int
    username: str
    password: str
    verify_ssl: bool
    download_dir: str
    ignore_camera_names: str
    start_time: datetime.time
    end_time: datetime.time
    verbose: bool


@dataclass
class EventCamera:
    id: int
    name: str
    ignore: bool
