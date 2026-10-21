import asyncio
import json
import re
from datetime import date, datetime
from hashlib import sha256
from urllib.parse import urlparse

import httpx
from dateutil.parser import parse as parse_date

from .config import Settings
from .models import Report, Review


class ServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def safe_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username else None


def text_field(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and not isinstance(value, (list, dict)):
            return str(value).strip()
    return ""


def normalize(rows: list, asin: str, settings: Settings) -> Report:
    report = Report(asin=asin, product_url=f"https://www.amazon.com/dp/{asin}", model=settings.llm_model,
                    scope=settings.bright_data_scope, latest_verified=settings.bright_data_latest_verified,
                    limit_verified=settings.bright_data_limit_verified, received_count=len(rows))
    seen: set[str] = set()
    records: list[Review] = []
    unknown_dates = 0
    for row in rows:
        if not isinstance(row, dict):
            report.excluded_count += 1
            continue
        if not report.product_name:
            report.product_name = text_field(row, "product_name", "product_title") or None
        body = text_field(row, "review_text", "review_content", "content", "text", "body")
        raw_rating = text_field(row, "rating", "review_rating", "review_stars")
        try:
            match = re.match(r"^\s*([1-5](?:\.\d+)?)\b", raw_rating)
            value = float(match.group(1)) if match else 0.0
            rating = int(value) if value.is_integer() else 0
            if not body or rating not in range(1, 6):
                raise ValueError()
        except (ValueError, TypeError):
            report.excluded_count += 1
            continue
        raw_date = text_field(row, "review_date", "date", "timestamp")
        normalized_date = None
        if raw_date:
            try:
                # Never fill a missing year or month with today's values.
                full_date = r"\b\d{4}-\d{2}-\d{2}\b|\b[A-Za-z]+\s+\d{1,2},?\s+\d{4}\b|\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"
                if not re.search(full_date, raw_date):
                    raise ValueError()
                parsed = parse_date(raw_date, fuzzy=True, default=datetime(1900, 1, 1)).date()
                if parsed > date.today():
                    raise ValueError()
                normalized_date = parsed.isoformat()
            except (ValueError, OverflowError):
                pass
        unknown_dates += normalized_date is None
        source = text_field(row, "asin", "product_asin").upper()
        source = source if re.fullmatch(r"[A-Z0-9]{10}", source) else None
        url = safe_url(row.get("review_url"))
        provider_id = text_field(row, "review_id", "id")
        title = text_field(row, "review_title", "title")
        key = provider_id or url or json.dumps([body, title, raw_date, rating, source], ensure_ascii=False)
        digest = sha256(key.encode()).hexdigest()[:20]
        if digest in seen:
            report.duplicate_count += 1
            continue
        seen.add(digest)
        records.append(Review(id=f"R-{digest}", requested_asin=asin, source_asin=source,
                              review_url=url, rating=rating, date_raw=raw_date, date=normalized_date,
                              title_original=title, body_original=body))
    records.sort(key=lambda r: r.date or "", reverse=True)
    report.capped_count = max(0, len(records) - settings.max_reviews)
    report.reviews = records[:settings.max_reviews]
    report.total = len(report.reviews)
    for review in report.reviews:
        report.stars[str(review.rating)] += 1
    if report.total:
        report.negative_percentage = round(100 * (report.stars["1"] + report.stars["2"]) / report.total, 1)
    if not report.latest_verified:
        report.warnings.append("数据源的最新评论覆盖尚未验证；本地日期排序不等于获取到了商品最新的评论。")
    if not report.limit_verified:
        report.warnings.append("供应商端采集数量上限尚未验证；当前仅保证进入分析的评论不超过配置上限。")
    if report.scope == "unknown":
        report.warnings.append("父／子 ASIN 评论范围未确认，不能视为具体子商品的独立样本。")
    if unknown_dates:
        report.warnings.append(f"{unknown_dates} 条原始记录日期缺失或无法可靠解析，最新排序可能不完整。")
    if report.capped_count:
        report.warnings.append(f"供应商返回超过上限的数据，{report.capped_count} 条未进入分析；采集上限验证未通过。")
        report.limit_verified = False
    if report.excluded_count:
        report.warnings.append(f"{report.excluded_count} 条缺少有效星级或正文，已排除。")
    if report.duplicate_count:
        report.warnings.append(f"已去除 {report.duplicate_count} 条重复记录。")
    if report.total < settings.max_reviews:
        report.warnings.append("返回不足上限仅代表当前可获取数量，不代表商品全部评论数量。")
    return report


class BrightData:
    base = "https://api.brightdata.com/datasets/v3"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def collect(self, asin: str) -> Report:
        settings = self.settings
        payload = json.loads(settings.bright_data_input_json)
        # Keep common count fields aligned with the server cap, but do not invent sort fields.
        for key in ("numOfReviews", "max_reviews", "limit"):
            if key in payload:
                payload[key] = settings.max_reviews
        payload["url"] = f"https://www.amazon.com/dp/{asin}"
        params = json.loads(settings.bright_data_query_json)
        params.update(dataset_id=settings.bright_data_dataset_id, include_errors="true")
        headers = {"Authorization": f"Bearer {settings.bright_data_api_key}"}
        print("\n========== Bright Data REQUEST ==========")
        print("Dataset ID:", settings.bright_data_dataset_id)
        print("Query 参数:", params)
        print("采集请求体:", json.dumps([payload], ensure_ascii=False))
        print("=========================================\n")
        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            try:
                # Never retry this POST blindly: the server may already have accepted it.
                response = await client.post(f"{self.base}/trigger", params=params, json=[payload])
                self.check(response)
                snapshot = response.json().get("snapshot_id")
                if not snapshot or not re.fullmatch(r"[A-Za-z0-9_-]+", snapshot):
                    raise ServiceError("PROVIDER_SCHEMA_ERROR", "采集服务未返回有效任务标识。请核对 Dataset ID 和输入字段。")
                while True:
                    await asyncio.sleep(settings.provider_poll_seconds)
                    progress = await client.get(f"{self.base}/progress/{snapshot}")
                    self.check(progress)
                    state = progress.json().get("status")
                    if state == "ready":
                        break
                    if state in ("failed", "error", "canceled", "cancelled"):
                        raise ServiceError("PROVIDER_REQUEST_ERROR", "Bright Data 采集任务失败，请在供应商控制台检查任务。")
                result = await client.get(f"{self.base}/snapshot/{snapshot}", params={"format": "json"})
                self.check(result)
                rows = result.json()
            except httpx.TimeoutException as exc:
                raise ServiceError("PROVIDER_TIMEOUT", "评论采集请求超时；供应商可能已接受任务，请先检查控制台，勿连续重复提交。") from exc
            except httpx.HTTPError as exc:
                raise ServiceError("PROVIDER_REQUEST_ERROR", "无法连接评论数据服务，请稍后重试。") from exc
            except (ValueError, AttributeError) as exc:
                raise ServiceError("PROVIDER_SCHEMA_ERROR", "采集响应格式不符合预期，请核对接口定义。") from exc
        if not isinstance(rows, list):
            raise ServiceError("PROVIDER_SCHEMA_ERROR", "采集结果不是评论数组，请检查供应商响应结构。")
        errors = [r for r in rows if isinstance(r, dict) and (r.get("error") or r.get("error_code"))]
        valid_rows = [r for r in rows if r not in errors]
        if errors and not valid_rows:
            raise ServiceError("PROVIDER_REQUEST_ERROR", "数据源返回采集错误，不能据此判断商品没有评论。请检查 Bright Data 任务详情。")
        report = normalize(valid_rows, asin, settings)
        if errors:
            report.warnings.append(f"数据源另有 {len(errors)} 条错误记录，采集可能不完整。")
        return report

    
    @staticmethod
    def check(response: httpx.Response) -> None:
        if response.is_error:
            print("\n========== Bright Data API ERROR ==========")
            print("请求地址:", response.request.url)
            print("HTTP 状态码:", response.status_code)
            print("错误响应:", response.text[:3000])
            print("===========================================\n")

        if response.status_code in (401, 403):
            raise ServiceError(
                "PROVIDER_AUTH_ERROR",
                "Bright Data 鉴权失败，请检查 API Key 和采集器权限。"
            )

        if response.is_error:
            raise ServiceError(
                "PROVIDER_REQUEST_ERROR",
                f"数据服务请求失败（HTTP {response.status_code}），请查看终端中的 Bright Data 原始错误。"
            )
