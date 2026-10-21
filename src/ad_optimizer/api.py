import asyncio
import logging
import secrets
from time import perf_counter
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .analysis import Analyzer
from .config import Settings, get_settings
from .exports import markdown_bytes, workbook_bytes
from .models import AnalysisRequest, ErrorInfo, Task, utcnow
from .providers import BrightData, ServiceError

logger = logging.getLogger(__name__)


class TaskStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tasks: dict[str, Task] = {}
        self.running: set[asyncio.Task] = set()
        self.lock = asyncio.Lock()

    def clean(self) -> None:
        now = utcnow()
        for key in list(self.tasks):
            expires = self.tasks[key].expires_at
            if expires and expires <= now:
                del self.tasks[key]

    async def execute(self, task: Task) -> None:
        started = perf_counter()
        analysis_started: float | None = None
        try:
            async with asyncio.timeout(self.settings.task_timeout_seconds):
                report = await BrightData(self.settings).collect(task.asin)
                task.result = report
                task.timings["collection_seconds"] = round(perf_counter() - started, 2)
                task.revision += 1
                if report.total:
                    task.status, task.stage_message = "analyzing", "正在翻译、分类并核验原文证据"
                    analysis_started = perf_counter()
                    def progress(completed: int, total: int, processed: int):
                        task.completed_batches, task.total_batches, task.processed_reviews = completed, total, processed
                        task.stage_message = f"已处理 {processed}/{report.total} 条，已通过分析 {report.analyzed_count} 条；批次 {completed}/{total}"
                        if completed == total:
                            task.stage_message += "，正在整理分类"
                        task.timings["analysis_seconds"] = round(perf_counter() - analysis_started, 2)
                        task.revision += 1
                    analyzer = Analyzer(self.settings)
                    analyzer.on_progress = progress
                    await analyzer.analyze(report)
                    task.timings["analysis_seconds"] = round(perf_counter() - analysis_started, 2)
                    if not report.analyzed_count:
                        raise ServiceError("LLM_OUTPUT_INVALID", "评论已获取，但模型分析未通过校验。原文可查看和导出，报告尚未完成。")
                task.status = "partial" if report.analyzed_count < report.total or report.analysis_incomplete else "completed"
                task.stage_message = "部分分析完成，请查看缺失说明" if task.status == "partial" else ("分析完成" if report.total else "当前未获取到有效评论")
        except TimeoutError:
            task.status, task.stage_message = "failed", "分析超时"
            task.error = ErrorInfo(code="TASK_TIMEOUT", message="任务超过运行时限；已获取的评论如有可查看。请先检查供应商任务状态。")
        except ServiceError as exc:
            task.status, task.stage_message = "failed", "分析未完成"
            task.error = ErrorInfo(code=exc.code, message=exc.message)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not log arbitrary provider payloads, keys or review text.
            logger.error("Analysis failed unexpectedly task=%s", task.id)
            task.status, task.stage_message = "failed", "分析遇到异常"
            task.error = ErrorInfo(code="INTERNAL_ERROR", message="处理失败，请检查服务端配置和接口兼容性。")
        finally:
            if analysis_started is not None:
                task.timings["analysis_seconds"] = round(perf_counter() - analysis_started, 2)
            task.timings["total_seconds"] = round(perf_counter() - started, 2)
            task.revision += 1
            if task.status in ("completed", "partial", "failed"):
                task.expires_at = utcnow() + timedelta(seconds=self.settings.result_ttl_seconds)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    store = TaskStore(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def cleanup():
            while True:
                await asyncio.sleep(30)
                store.clean()
        cleaner = asyncio.create_task(cleanup())
        yield
        cleaner.cancel()
        pending = [cleaner, *store.running]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    app = FastAPI(title="Review Lens · 评论分析", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(CORSMiddleware, allow_origins=config.allowed_origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.middleware("http")
    async def no_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "configured": not config.missing(), "missing": config.missing(), "max_reviews": config.max_reviews,
                "latest_verified": config.bright_data_latest_verified, "limit_verified": config.bright_data_limit_verified}

    @app.post("/api/analyses", status_code=202)
    async def create_analysis(body: AnalysisRequest):
        if config.missing():
            raise HTTPException(503, {"code": "CONFIGURATION_ERROR", "message": "请先配置服务端 Bright Data 与模型 API，缺少：" + ", ".join(config.missing())})
        async with store.lock:
            store.clean()
            if sum(t.status in ("fetching", "analyzing") for t in store.tasks.values()) >= config.max_active_analyses:
                raise HTTPException(429, {"code": "SERVICE_BUSY", "message": "服务正在分析其他商品，请稍后重试。首版不排队。"}, headers={"Retry-After": "10"})
            task = Task(id=secrets.token_urlsafe(24), asin=body.asin)
            store.tasks[task.id] = task
            runner = asyncio.create_task(store.execute(task))
            store.running.add(runner)
            runner.add_done_callback(store.running.discard)
        return {"task_id": task.id, "status": task.status, "status_url": f"/api/analyses/{task.id}"}

    def get_task(task_id: str) -> Task:
        store.clean()
        task = store.tasks.get(task_id)
        if not task:
            raise HTTPException(404, {"code": "TASK_EXPIRED", "message": "任务不存在或已过期，请重新分析。"})
        return task

    @app.get("/api/analyses/{task_id}", response_model=Task)
    async def read_task(task_id: str, include_result: bool = True):
        task = get_task(task_id)
        if not include_result:
            return JSONResponse(task.model_dump(mode="json", exclude={"result"}))
        return task

    @app.get("/api/analyses/{task_id}/export")
    async def export(task_id: str, format: Literal["xlsx", "md"]):
        task = get_task(task_id)
        if task.status in ("fetching", "analyzing") or task.result is None:
            raise HTTPException(409, {"code": "NOT_READY", "message": "结果尚不可导出。"})
        report = task.result.model_copy(deep=True)
        if task.status in ("failed", "partial"):
            report.warnings.append("此报告未完成全部分析。" + (task.error.message if task.error else ""))
        partial = "-partial" if task.status != "completed" else ""
        filename = f"{task.asin}-{report.generated_at:%Y%m%d-%H%M%S}{partial}.{format}"
        content = await asyncio.to_thread(workbook_bytes if format == "xlsx" else markdown_bytes, report)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else "text/markdown; charset=utf-8"
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    return app


app = create_app()
