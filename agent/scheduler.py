"""Cron Scheduler · Hermes Agent 启发 · APScheduler 定时任务。

示例任务：
- 每周一 8:30 自动生成上周周报
- 每日 9:00 daily digest
- 每小时检查 pending tasks

Cron 定义存 .larkmentor/schedules/*.yaml
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.scheduler")


class CronScheduler:
    def __init__(self) -> None:
        self._apscheduler = None
        self.jobs: List[Dict[str, Any]] = []
        self.schedules_dir = Path.cwd() / ".larkmentor" / "schedules"
        self.schedules_dir.mkdir(parents=True, exist_ok=True)
        self._load_schedules()

    def _load_schedules(self) -> None:
        for f in self.schedules_dir.glob("*.yaml"):
            try:
                import yaml
                data = yaml.safe_load(f.read_text())
                self.jobs.append(data)
            except Exception as e:
                logger.debug("schedule load failed %s: %s", f, e)

    def start(self) -> bool:
        """Boot APScheduler and register all jobs."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning("APScheduler not installed, cron disabled")
            return False

        if self._apscheduler:
            return True
        sched = BackgroundScheduler()
        for job in self.jobs:
            cron = job.get("cron", "0 9 * * *")  # daily 9am default
            try:
                trig = CronTrigger.from_crontab(cron)
                sched.add_job(
                    self._make_runner(job),
                    trigger=trig,
                    name=job.get("name", "unnamed"),
                    id=job.get("name", "unnamed"),
                )
                logger.info("cron registered: %s @ %s", job.get("name"), cron)
            except Exception as e:
                logger.warning("failed to add cron job %s: %s", job.get("name"), e)
        sched.start()
        self._apscheduler = sched
        return True

    def _make_runner(self, job: Dict[str, Any]):
        def _run():
            try:
                kind = job.get("kind", "pilot")
                task = job.get("task", "")
                user_open_id = job.get("user_open_id", "")
                tenant_id = job.get("tenant_id", "default")
                logger.info("cron run %s: %s", job.get("name"), kind)
                if kind == "pilot":
                    from bot.handlers_v4 import _run_pilot
                    _run_pilot(task, user_open_id=user_open_id, chat_id="", tenant_id=tenant_id)
                elif kind == "weekly_report":
                    from agent.tools.mentor_tools import weekly_report
                    weekly_report(user_open_id=user_open_id)
                elif kind == "shell":
                    import subprocess
                    subprocess.run(job.get("command", "true"), shell=True, timeout=300)
            except Exception as e:
                logger.exception("cron %s failed: %s", job.get("name"), e)
        return _run

    def stop(self) -> None:
        if self._apscheduler:
            self._apscheduler.shutdown(wait=False)
            self._apscheduler = None

    def snapshot(self) -> Dict[str, Any]:
        return {"jobs": self.jobs, "running": bool(self._apscheduler)}


_singleton: Optional[CronScheduler] = None


def default_scheduler() -> CronScheduler:
    global _singleton
    if _singleton is None:
        _singleton = CronScheduler()
    return _singleton
