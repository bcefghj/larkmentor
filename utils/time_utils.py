import time
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))


def now_cst() -> datetime:
    return datetime.now(CST)


def now_ts() -> int:
    return int(time.time())


def fmt_time(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = now_cst()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分钟"
    hours = minutes // 60
    remaining = minutes % 60
    if remaining:
        return f"{hours}小时{remaining}分钟"
    return f"{hours}小时"
