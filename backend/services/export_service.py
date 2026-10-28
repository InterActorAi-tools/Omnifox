"""ExportComments extraction: fetch a post's comments (replies flattened), then analyse them."""
import importlib.metadata
import io
import os
import time
import uuid
import asyncio
import fcntl
import tempfile
from contextlib import asynccontextmanager
import aiohttp
import pandas as pd
import logging
from exportcomments import ExportComments
from exportcomments.exceptions import RateLimitError
from typing import Dict, Any, Optional, List

from config import EXPORTCOMMENTS_API_KEY, EXPORTCOMMENTS_MAX_CONCURRENT, UPLOAD_FOLDER
from task_manager import TaskStatus, smooth_progress, user_error
from utils.crypto import write_file
from services.processing import ProcessingService
from utils.url_safety import (
    PinnedResolver,
    UnsafeURLError,
    validate_external_url,
)

# Allowlist for SSRF-safe outbound fetches of ExportComments-issued
# download URLs. Suffix entries (leading dot) match the apex and any
# subdomain; entries without a leading dot must match exactly. Kept
# narrow on purpose - the upstream serves downloads from a small set of
# CDN-style hostnames.
_EXPORTCOMMENTS_ALLOWED_HOSTS = (
    ".exportcomments.com",
)

logger = logging.getLogger(__name__)

# One lock file per slot; flock works across the Gunicorn workers and is
# released by the OS if a worker dies.
EXPORT_SLOT_DIR = os.path.join(tempfile.gettempdir(), "omnifox_export_slots")


@asynccontextmanager
async def export_slot(task_id: str, task_manager: Any):
    """Hold one of EXPORTCOMMENTS_MAX_CONCURRENT slots while an ExportComments job runs.

    The API key is shared with OmniCat (5 jobs at once), so OmniFox keeps to a few.
    """
    os.makedirs(EXPORT_SLOT_DIR, exist_ok=True)
    waiting = False
    while True:
        for n in range(EXPORTCOMMENTS_MAX_CONCURRENT):
            lock = open(os.path.join(EXPORT_SLOT_DIR, f"{n}.lock"), "w")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                continue
            try:
                yield
            finally:
                lock.close()  # releases the lock
            return
        if not waiting:
            task_manager.update_task_status(task_id, TaskStatus.EXTRACTING, smooth_progress.get_smooth_progress('EXTRACTING', 0.0), "Waiting for other exports to finish...")
            waiting = True
        await asyncio.sleep(5)
        if task_manager.is_task_cancelled(task_id):
            raise asyncio.CancelledError

class PlatformColumnMapper:
    """Enhanced mapper with reply support"""
    
    def __init__(self):
        self.text_column_mapping = {
            'comment_body': 'Text',
            'message': 'Text',
            'text': 'Text',
            'content': 'Text',
            'comment_text': 'Text',
            'body': 'Text',
        }
        
        self.metadata_mappings = {
            'author_name': 'Author Name',
            'username': 'Author Name', 
            'name': 'Author Name',
            'user_name': 'Author Name',
            'profile_name': 'Author Name',
            'like_count': 'Likes',
            'likes': 'Likes',
            'likes_count': 'Likes',
            'reaction_count': 'Likes',
            'time': 'Time',
            'created_at': 'Time',
            'timestamp': 'Time',
            'date': 'Time',
            'published_at': 'Time',
            'reply_count': 'Reply Count',
            'replies': 'Replies',
            'is_reply': 'Is Reply',
            'parent_comment_id': 'Parent ID',
            'comment_id': 'Comment ID',
            'id': 'Comment ID',
            'post_id': 'Post ID',
            'video_id': 'Video ID',
            'author_thumbnail': 'Author Avatar',
            'profile_image': 'Author Avatar',
            'avatar_url': 'Author Avatar',
            'profile_url': 'Profile URL',
            'profile_id': 'Profile ID',
            'is_verified_user': 'Verified',
            'is_hearted': 'Hearted',
            'is_pinned': 'Pinned',
            'is_liked': 'User Liked',
            'author_is_channel_owner': 'Channel Owner',
            'comment_url': 'Comment URL',
            'url': 'Comment URL',
            'comment_link': 'Comment URL',
            'permalink': 'Comment URL',
            'created_time': 'Time',
            'attachment_type': 'Attachment Type',
            'attachment_url': 'Attachment URL',
            'media_type': 'Media Type',
            'reel_id': 'Reel ID',
            'video_url': 'Video URL',
            'channel_url': 'Channel URL',
            'author_channel_url': 'Author Channel URL',
            'video_link': 'Video URL',
            'post_url': 'Post URL',
            'shortcode': 'Shortcode',
            'post_link': 'Post URL',
            'share_url': 'Share URL',
        }
        
        self.platform_patterns = {
            'youtube': ['video_id', 'channel_id', 'comment_body'],
            'instagram': ['shortcode', 'username', 'message'],
            'tiktok': ['profile_short_id', 'video_url'],
            'facebook': ['message', 'created_time', 'comment_url', 'reel_id'],
            'twitter': ['tweet_id', 'user_screen_name'],
        }
    
    def find_text_column(self, columns: list) -> Optional[str]:
        columns_lower = {col.lower(): col for col in columns}
        for potential_col, _ in self.text_column_mapping.items():
            if potential_col in columns_lower:
                found_col = columns_lower[potential_col]
                logger.info(f"✅ Found text column: '{found_col}'")
                return found_col
        text_keywords = ['message', 'comment', 'text', 'content', 'body', 'caption']
        for keyword in text_keywords:
            for col_lower, original_col in columns_lower.items():
                if keyword in col_lower:
                    logger.info(f"✅ Found text column: '{original_col}' (partial match: {keyword})")
                    return original_col
        logger.error(f"❌ No text column found in: {columns}")
        return None
    
    def map_columns(self, df: pd.DataFrame, platform: str = 'unknown') -> pd.DataFrame:
        logger.info(f"=== COLUMN MAPPING FOR {platform.upper()} ===")
        text_column = self.find_text_column(df.columns.tolist())
        if not text_column:
            raise ValueError(f"No text column found in data. Available columns: {list(df.columns)}")
        
        mapped_df = pd.DataFrame()
        mapped_df['Text'] = df[text_column].fillna('')
        logger.info(f"🔗 Mapped text column: '{text_column}' → 'Text'")
        
        columns_lower = {col.lower(): col for col in df.columns}
        mapped_count = 0
        mapped_sources = set()
        for original_pattern, standard_name in self.metadata_mappings.items():
            # First match wins: e.g. "comment_id" and "id" both map to "Comment ID";
            # a later one must not overwrite it (the other keeps its own column).
            if original_pattern in columns_lower and standard_name not in mapped_df.columns:
                original_col = columns_lower[original_pattern]
                mapped_df[standard_name] = df[original_col]
                mapped_sources.add(original_col)
                mapped_count += 1
                logger.info(f"📊 Mapped: '{original_col}' → '{standard_name}'")

        for col in df.columns:
            if col != text_column and col not in mapped_sources:
                clean_name = col.replace('_', ' ').replace('-', ' ').title()
                counter = 1
                original_clean_name = clean_name
                while clean_name in mapped_df.columns:
                    clean_name = f"{original_clean_name} {counter}"
                    counter += 1
                mapped_df[clean_name] = df[col]
        
        logger.info(f"✅ Column mapping complete: {mapped_count} standard mappings")
        logger.info(f"📋 Final columns ({len(mapped_df.columns)}): {list(mapped_df.columns)}")
        return mapped_df

column_mapper = PlatformColumnMapper()


def _write_excel(df: pd.DataFrame, path: str) -> None:
    # Comments are untrusted text: never let "=..." become a live formula.
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter", engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}}) as writer:
        df.to_excel(writer, index=False)
    write_file(path, buffer.getvalue())

async def process_and_cache(task_id: str, client_id: str, extracted_filename: str, url_hash: str,
                            project: str = "default", post_context: str = "") -> Optional[Dict[str, Any]]:
    """Analyse an extracted file, cache the result for its URL and complete the task.
    Returns the result, or None if the run was cancelled or failed (the task says which)."""
    from cache_service import cache_service
    from task_manager import task_manager

    file_path = os.path.join(UPLOAD_FOLDER, client_id, extracted_filename)
    if not os.path.exists(file_path):
        task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, "Extracted file not found")
        return None
    try:
        result_data = await ProcessingService().process_file_contents(
            file_path, client_id, extracted_filename, task_id, task_manager,
            project, post_context=post_context, operation_type="url_extraction"
        )
    except asyncio.CancelledError:
        return None  # processing already marked the task cancelled
    except Exception as e:
        logger.error(f"❌ Error in processing: {str(e)}")
        task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, f"Processing error: {user_error(e)}")
        return None

    if result_data is None:  # cancelled before processing started
        return None

    keep = ("sentiment_counts", "overall_summary", "positive_context", "neutral_context",
            "negative_context", "total_comments", "objective_results")
    cache_service.cache_url_processing(url_hash, result_data["new_filename"], {k: result_data.get(k) for k in keep})
    task_manager.update_task_status(
        task_id, TaskStatus.COMPLETED,
        smooth_progress.get_smooth_progress('COMPLETED', 1.0),
        "Processing completed successfully", result_data
    )
    return result_data


class ExportCommentsService:
    """Enhanced service with nested reply flattening and post context support"""
    
    def __init__(self):
        self.api_key = EXPORTCOMMENTS_API_KEY
        self.export_client = ExportComments(self.api_key)

    # Fields to inherit from parent comment if reply doesn't have its own value.
    # Covers all platforms: Facebook, YouTube, Instagram, TikTok.
    PARENT_FIELDS_TO_INHERIT = [
        # Common
        'comment_url', 'permalink',
        # YouTube
        'video_id', 'channel_id', 'channel_url', 'author_channel_url', 'video_link',
        # Facebook
        'reel_id', 'post_id', 'video_url',
        # Instagram
        'shortcode', 'post_url', 'post_link',
        # TikTok
        'share_url',
    ]

    async def _create_job(self, task_id: str, task_manager: Any, url: str):
        """Start an export; while the shared key is at its limit (OmniCat runs jobs too), wait and try again."""
        for attempt in range(40):  # about 20 minutes
            try:
                # The ExportComments SDK is synchronous (requests); run it in a
                # thread so it does not block the worker's event loop.
                return await asyncio.to_thread(
                    self.export_client.jobs.create,
                    url=url,
                    options={"replies": True, "limit": 50000, "minTimestamp": 0},
                )
            except RateLimitError:
                if attempt == 39:
                    raise
            task_manager.update_task_status(task_id, TaskStatus.EXTRACTING, smooth_progress.get_smooth_progress('EXTRACTING', 0.0), "ExportComments is busy, waiting for a free slot...")
            await asyncio.sleep(30)
            if task_manager.is_task_cancelled(task_id):
                raise asyncio.CancelledError

    def flatten_nested_replies(self, raw_data: List[Dict]) -> List[Dict]:
        """Flatten nested replies into separate records, inheriting parent URL fields"""
        flattened_records = []
        original_count = len(raw_data)
        logger.info(f"🔧 Flattening nested reply data from {original_count} records...")

        for record in raw_data:
            main_comment = record.copy()
            main_comment['is_reply'] = False
            main_comment['parent_comment_id'] = None
            main_comment['replies'] = None
            flattened_records.append(main_comment)

            replies_raw = record.get('replies')
            if replies_raw:
                parent_comment_id = record.get('comment_id')
                parent_fields = {f: record.get(f) for f in self.PARENT_FIELDS_TO_INHERIT if record.get(f)}

                if isinstance(replies_raw, dict):
                    reply_items = [v for v in replies_raw.values() if isinstance(v, dict)]
                elif isinstance(replies_raw, list):
                    reply_items = [r for r in replies_raw if isinstance(r, dict)]
                else:
                    reply_items = []

                for reply_data in reply_items:
                    reply_record = reply_data.copy()
                    reply_record['is_reply'] = True
                    reply_record['parent_comment_id'] = parent_comment_id
                    reply_record['replies'] = None
                    for field, value in parent_fields.items():
                        if not reply_record.get(field):
                            reply_record[field] = value
                    flattened_records.append(reply_record)

        main_comments = len([r for r in flattened_records if not r.get('is_reply', False)])
        reply_comments = len([r for r in flattened_records if r.get('is_reply', False)])
        logger.info(f"✅ Flattening complete: Main={main_comments}, Replies={reply_comments}, Total={len(flattened_records)}")
        return flattened_records

    async def background_extract_and_cache_v2(self, task_id: str, client_id: str,
                                              payload: Any, cache_service: Any, task_manager: Any,
                                              user_id: int = None, project: str = "default"):
        """Enhanced background extraction with reply flattening, post context, and user tracking"""
        try:
            task_manager.update_task_status(
                task_id, TaskStatus.EXTRACTING,
                smooth_progress.get_smooth_progress('EXTRACTING', 0.0),
                "Connecting to ExportComments API..."
            )

            if task_manager.is_task_cancelled(task_id):
                return

            post_context = getattr(payload, 'post_context', '')
            if post_context:
                logger.info("📝 Extraction with post context")

            async with export_slot(task_id, task_manager):
                try:
                    job = await self._create_job(task_id, task_manager, payload.url)
                    guid = job.body["guid"]
                    detected_platform = self._detect_platform_from_url(payload.url)

                    task_manager.update_task_status(
                        task_id, TaskStatus.EXTRACTING,
                        smooth_progress.get_smooth_progress('EXTRACTING', 0.1),
                        f"Export job created, extracting {detected_platform} comments with replies..."
                    )

                except Exception as e:
                    task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, f"Failed to create export job: {user_error(e)}")
                    return

                max_wait_attempts = 720
                wait_attempt = 0
                start_time = time.monotonic()
                check = None  # Will hold the last successful check response

                while wait_attempt < max_wait_attempts:
                    if task_manager.is_task_cancelled(task_id):
                        task_manager.update_task_status(task_id, TaskStatus.CANCELLED, 0, "Extraction cancelled by user")
                        return

                    try:
                        check = await asyncio.to_thread(self.export_client.jobs.check, guid=guid)
                        body = check.body
                        status = body.get("status", "unknown")

                        # --- Real progress from API -------------------------------------------
                        # ExportComments returns `total` (expected) and `total_exported` (done so far).
                        # Fall back to the legacy `percent` field if those are absent.
                        total: int = int(body.get("total") or 0)
                        total_exported: int = int(body.get("total_exported") or body.get("commentsCount") or 0)

                        if total > 0:
                            real_pct = min(total_exported / total, 1.0)  # 0.0 – 1.0
                        else:
                            # API hasn't reported totals yet — use legacy percent or time-based fallback
                            legacy_pct = int(body.get("percent", 0))
                            real_pct = legacy_pct / 100 if legacy_pct else min(0.9, wait_attempt / max_wait_attempts)

                        # Map into the EXTRACTING phase bucket kept under 95 % until truly done
                        extraction_fraction = real_pct * 0.95
                        current_progress = smooth_progress.get_smooth_progress('EXTRACTING', extraction_fraction)

                        elapsed_s = time.monotonic() - start_time
                        if total > 0:
                            message = (
                                f"Extracting {detected_platform} comments... "
                                f"({total_exported:,}/{total:,} | {elapsed_s:.0f}s)"
                            )
                        else:
                            elapsed_min = int(elapsed_s // 60)
                            message = f"Extracting {detected_platform} comments... ({elapsed_min}min)"

                        logger.info(
                            f"[{task_id}] status={status} | {total_exported}/{total} "
                            f"({real_pct*100:.1f}%) | progress={current_progress}"
                        )
                        task_manager.update_task_status(task_id, TaskStatus.EXTRACTING, current_progress, message)

                        if status == "done":
                            task_manager.update_task_status(
                                task_id, TaskStatus.EXTRACTING,
                                smooth_progress.get_smooth_progress('EXTRACTING', 1.0),
                                f"Extraction complete — {total_exported:,} comment(s) downloaded, preparing data..."
                            )
                            break
                        elif status == "error":
                            error_msg = body.get("error") or body.get("message") or "Unknown API error"
                            task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, f"Export failed: {error_msg}")
                            return
                        elif status == "stopped":
                            task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, "Export job was stopped on API side")
                            return

                        await asyncio.sleep(10)
                        wait_attempt += 1

                    except Exception as e:
                        logger.error(f"Error checking job status: {str(e)}")
                        await asyncio.sleep(10)
                        wait_attempt += 1

                if wait_attempt >= max_wait_attempts:
                    task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, "Export timed out after 2 hours")
                    return

            task_manager.update_task_status(
                task_id, TaskStatus.EXTRACTING,
                smooth_progress.get_smooth_progress('PROCESSING_INIT', 0.0),
                "Downloading extracted comments and replies..."
            )

            if task_manager.is_task_cancelled(task_id):
                return

            try:
                download_link = check.body.get("json_url") or check.body.get("download_link")
                if not download_link:
                    task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, "No download URL returned by API")
                    return

                # SSRF defense (C7): the download URL is supplied by the
                # upstream API response. Validate scheme + hostname +
                # resolved IP, then pin the connection to the vetted IPs
                # so DNS rebinding cannot redirect us to an internal host.
                try:
                    validated = validate_external_url(
                        download_link,
                        allowed_suffixes=_EXPORTCOMMENTS_ALLOWED_HOSTS,
                    )
                except UnsafeURLError as exc:
                    logger.error(f"Refused unsafe download URL: {exc}")
                    task_manager.update_task_status(
                        task_id, TaskStatus.FAILED, 0,
                        "Download blocked: untrusted URL returned by upstream",
                    )
                    return

                headers = {
                    'X-AUTH-TOKEN': self.api_key,
                    'Content-Type': 'application/json',
                    'User-Agent': f'python-sdk-{importlib.metadata.version("exportcomments")}',
                }

                timeout = aiohttp.ClientTimeout(total=180)
                connector = aiohttp.TCPConnector(
                    resolver=PinnedResolver(
                        validated.hostname,
                        validated.port,
                        validated.resolved_ips,
                    ),
                )
                async with aiohttp.ClientSession(
                    timeout=timeout, connector=connector
                ) as session:
                    is_json = download_link.endswith('.json') or 'json' in download_link
                    # allow_redirects=False: a 3xx would otherwise let the
                    # upstream hand off to an arbitrary URL after our checks.
                    async with session.get(
                        validated.url, headers=headers, allow_redirects=False
                    ) as response:
                        if response.status == 200:
                            if is_json:
                                comments_data = await response.json()
                            else:
                                xlsx_bytes = await response.read()
                                df = await asyncio.to_thread(pd.read_excel, io.BytesIO(xlsx_bytes), keep_default_na=False, na_values=[""], dtype=object)
                                comments_data = df.to_dict('records')
                                logger.info(f"📥 Downloaded XLSX fallback, parsed {len(comments_data)} records")

                            task_manager.update_task_status(
                                task_id, TaskStatus.EXTRACTING,
                                smooth_progress.get_smooth_progress('PROCESSING_INIT', 0.5),
                                "Processing and flattening reply data..."
                            )

                            flattened_data = self.flatten_nested_replies(comments_data)

                            result = await self._process_extracted_data_universal(flattened_data, client_id, payload)

                            if result:
                                url_hash = cache_service.cache_url_extraction(
                                    payload.url, payload.project, client_id,
                                    result["comments_count"], result["filename"]
                                )

                                task_manager.update_task_status(
                                    task_id, TaskStatus.PROCESSING,
                                    smooth_progress.get_smooth_progress('PROCESSING_INIT', 1.0),
                                    "Starting sentiment analysis..."
                                )

                                await process_and_cache(
                                    task_id, client_id, result["filename"], url_hash, project, post_context
                                )
                            else:
                                task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, "No valid comments found")

                        else:
                            task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, f"Download failed: {response.status}")
                            return

            except Exception as e:
                task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, f"Download error: {user_error(e)}")
                return

        except asyncio.CancelledError:
            task_manager.update_task_status(task_id, TaskStatus.CANCELLED, 0, "Extraction cancelled by user")
            return
        except Exception as e:
            task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, f"Extraction error: {user_error(e)}")
            logger.error(f"Error in background_extract_and_cache_v2: {str(e)}")

    def _detect_platform_from_url(self, url: str) -> str:
        url_lower = url.lower()
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower: return 'youtube'
        elif 'instagram.com' in url_lower: return 'instagram'
        elif 'tiktok.com' in url_lower: return 'tiktok'
        elif any(domain in url_lower for domain in ['facebook.com', 'fb.com', 'fb.watch', 'facebook.com/reel', 'facebook.com/share/r']): return 'facebook'
        elif 'twitter.com' in url_lower or 'x.com' in url_lower: return 'twitter/X'
        else: return 'social media'

    async def _process_extracted_data_universal(self, comments_data: list, client_id: str, payload: Any) -> Dict[str, Any]:
        """Process extracted comments data with reply support"""
        try:
            df = pd.DataFrame(comments_data)
            logger.info(f"=== PROCESSING FLATTENED DATA: {len(df)} records ===")

            if len(df) == 0:
                logger.error("❌ No comments data received")
                return None

            platform = self._detect_platform_from_url(payload.url)

            # Build comment_url if not returned by the API (platform-specific construction).
            # This runs on the already-flattened data so both main comments and replies get URLs.
            # flatten_nested_replies propagates comment_url to replies via PARENT_FIELDS_TO_INHERIT.
            if 'comment_url' not in df.columns:
                if platform == 'facebook':
                    # <base_post_url>?comment_id=<comment_id>
                    base_url = payload.url.split('?')[0]
                    if 'comment_id' in df.columns:
                        df['comment_url'] = df['comment_id'].apply(
                            lambda cid: f"{base_url}?comment_id={cid}" if pd.notna(cid) else None
                        )
                        logger.info(f"🔗 Built comment_url for {len(df)} Facebook records")

                elif platform == 'instagram':
                    # https://www.instagram.com/p/<shortcode>/?comment_id=<comment_id>
                    if 'shortcode' in df.columns and 'comment_id' in df.columns:
                        df['comment_url'] = df.apply(
                            lambda row: f"https://www.instagram.com/p/{row['shortcode']}/?comment_id={row['comment_id']}"
                            if pd.notna(row['shortcode']) and pd.notna(row['comment_id']) else None,
                            axis=1
                        )
                        logger.info(f"🔗 Built comment_url for {len(df)} Instagram records")

                elif platform == 'youtube':
                    # https://www.youtube.com/watch?v=<video_id>&lc=<comment_id>
                    if 'video_id' in df.columns and 'comment_id' in df.columns:
                        df['comment_url'] = df.apply(
                            lambda row: f"https://www.youtube.com/watch?v={row['video_id']}&lc={row['comment_id']}"
                            if pd.notna(row['video_id']) and pd.notna(row['comment_id']) else None,
                            axis=1
                        )
                        logger.info(f"🔗 Built comment_url for {len(df)} YouTube records")

            processed_df = column_mapper.map_columns(df, platform)

            if 'Text' not in processed_df.columns:
                logger.error("❌ Failed to map text column")
                return None

            processed_df = processed_df[processed_df['Text'].astype(str).str.strip() != '']
            processed_df.dropna(subset=['Text'], inplace=True)

            if len(processed_df) == 0:
                logger.error("❌ No valid comments found after filtering")
                return None

            for col in ['Likes', 'Reply Count']:
                if col in processed_df.columns:
                    processed_df[col] = pd.to_numeric(processed_df[col], errors='coerce').fillna(0).astype(int)

            client_folder = os.path.join(UPLOAD_FOLDER, client_id)
            os.makedirs(client_folder, exist_ok=True)

            # Random suffix: two extractions in the same second must not overwrite each other.
            extracted_filename = f"extracted_{platform}_comments_with_replies_{int(time.time())}_{uuid.uuid4().hex[:6]}.xlsx"
            file_path = os.path.join(client_folder, extracted_filename)

            await asyncio.to_thread(_write_excel, processed_df, file_path)

            logger.info(f"=== SAVED EXTRACTED FILE ({len(processed_df)} rows) ===")

            return {
                "filename": extracted_filename,
                "comments_count": len(processed_df),
                "file_path": file_path,
                "platform": platform,
                "columns_included": list(processed_df.columns),
                "includes_replies": True
            }

        except Exception as e:
            logger.error(f"❌ Error processing extracted data: {str(e)}")
            return None
