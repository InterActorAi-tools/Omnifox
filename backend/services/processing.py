"""
Comment processing service for sentiment analysis and data processing - COMPLETE MERGED VERSION
Includes:
- Production logging
- Post Context support
- Cancellation checks
- Correct Analytics tracking
"""
import os
import time
import uuid
import asyncio
import pandas as pd
import logging
from collections import Counter
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

# Import your analytics module (make sure this path is correct for your project structure)
from simple_analytics import simple_analytics 
from config import settings, UPLOAD_FOLDER
from database import SessionLocal
from models import Project
from task_manager import TaskStatus, smooth_progress, user_error
from services.gemini_service import get_gemini
from utils.file_utils import read_and_clean_excel_enhanced, create_excel_with_charts_enhanced

logger = logging.getLogger(__name__)

# Shared by every ProcessingService instance. A pool per instance leaked
# up to max_workers idle threads for each request that built a service.
_processing_executor = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="processing")

def project_objectives(project: str) -> List[str]:
    """The campaign objectives saved on the project (none for an unknown project)."""
    db = SessionLocal()
    try:
        row = db.query(Project).filter(Project.name == project).first()
        return list(row.objectives or []) if row else []
    finally:
        db.close()


def objective_results(objectives: List[str], scores: List[List[Dict]], summaries: List[str]) -> List[Dict]:
    """Per objective: stance counts over the comments relevant to it, % met
    (share of relevant comments that support it), average alignment and the AI summary."""
    results = []
    for k, objective in enumerate(objectives):
        relevant = [s[k] for s in scores if s[k]["stance"] != "not_relevant"]
        counts = Counter(s["stance"] for s in relevant)
        results.append({
            "objective": objective,
            "relevant_comments": len(relevant),
            "supports": counts["supports"],
            "neutral": counts["neutral"],
            "against": counts["against"],
            "percent_met": round(100 * counts["supports"] / len(relevant), 1) if relevant else None,
            "average_alignment": round(sum(s["alignment"] for s in relevant) / len(relevant), 2) if relevant else None,
            "summary": summaries[k],
        })
    return results


class ProcessingService:
    """Service for processing comments with production logging and strict row filtering"""
    
    def __init__(self):
        self.gemini_service = get_gemini()
        self.thread_pool = _processing_executor
        
        # Production logging: Track processing statistics
        self._processing_stats = {
            'total_processed': 0,
            'total_failed': 0,
            'last_batch_size': 0
        }
    
    def _log_processing_milestone(self, message: str, force_log: bool = False):
        """Log processing milestones based on environment"""
        if settings.debug or force_log:
            logger.info(message)
        elif not settings.debug:
            # Production: Only log major milestones
            logger.warning(message)
    
    # 🔥 UPDATED: Added post_context parameter (From Dev Version)
    async def process_file_contents(self, file_path: str, client_id: str, 
                                  base_filename: str, task_id: str = None, 
                                  task_manager=None, project: str = "default",
                                  progress_callback=None, post_context: str = None,
                                  objectives: Optional[List[str]] = None) -> Dict[str, Any]:
        """Process file contents with optional post context. Comments are also scored
        against the project's campaign objectives (looked up when not given)."""
        try:
            if objectives is None:
                objectives = await asyncio.to_thread(project_objectives, project)

            # CHECK FOR CANCELLATION
            if task_manager and task_id and task_manager.is_task_cancelled(task_id):
                logger.info(f"Task {task_id} cancelled before processing started")
                return None
            
            if progress_callback:
                progress_callback(0, 100)
            
            loop = asyncio.get_event_loop()
            file_data = await loop.run_in_executor(self.thread_pool, read_and_clean_excel_enhanced, file_path)
            
            if not file_data or not file_data.get('texts'):
                raise ValueError("No valid text found in file")
            
            all_texts = file_data['texts']
            metadata_df = file_data.get('metadata_df')
            
            self._log_processing_milestone(f"📄 Processing {len(all_texts)} comments from {base_filename}")
            
            if post_context:
                logger.info("📝 Using post context")
                
            if metadata_df is not None and settings.debug:
                logger.info(f"Metadata columns: {list(metadata_df.columns)}")
            
            if task_manager and task_id:
                task_manager.update_task_status(
                    task_id, TaskStatus.PROCESSING, 
                    smooth_progress.get_smooth_progress('PROCESSING', 0.1),
                    "Starting sentiment analysis..."
                )
            
            if progress_callback:
                progress_callback(5, 100)
            
            # 🔥 Pass post_context to processing
            result_data = await self._process_comments_in_chunks_enhanced(
                all_texts, metadata_df, client_id, base_filename, task_id, 
                task_manager, project, progress_callback, post_context, objectives
            )
            
            return result_data
            
        except asyncio.CancelledError:
            logger.info(f"Processing cancelled for task {task_id}")
            if task_manager and task_id:
                task_manager.update_task_status(task_id, TaskStatus.CANCELLED, 0, "Processing cancelled by user")
            raise
        except Exception as e:
            logger.error(f"Error in process_file_contents: {str(e)}")
            if task_manager and task_id:
                task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, f"Processing failed: {user_error(e)}")
            raise
    
    # 🔥 UPDATED: Added post_context parameter
    async def _process_comments_in_chunks_enhanced(self, all_texts: List[str], metadata_df: Optional[pd.DataFrame],
                                                 client_id: str, base_filename: str, task_id: str = None,
                                                 task_manager=None, project: str = "default", 
                                                 progress_callback=None, post_context: str = None,
                                                 objectives: List[str] = ()) -> Dict[str, Any]:
        """Process comments with optional post context"""
        total_comments = len(all_texts)
        self._processing_stats['last_batch_size'] = total_comments
        
        self._log_processing_milestone(f"🔄 Processing {total_comments} comments")
        
        if post_context:
            logger.info("📝 Post context enabled for better analysis")
        
        if task_manager and task_id:
            task_manager.update_task_status(
                task_id, TaskStatus.PROCESSING, 
                smooth_progress.get_smooth_progress('PROCESSING', 0.2),
                "Processing comments..."
            )
        
        def gemini_progress_callback(current, total):
            if task_manager and task_id and task_manager.is_task_cancelled(task_id):
                logger.info(f"Task {task_id} was cancelled during processing")
                raise asyncio.CancelledError("Task cancelled by user")
            
            if total > 0:
                phase_progress = current / total
                overall_progress = smooth_progress.get_smooth_progress('PROCESSING', 0.2 + (phase_progress * 0.6))
                
                if phase_progress < 0.3:
                    message = f"Analyzing comments with AI... ({current} processed)"
                elif phase_progress < 0.7:
                    message = f"Processing sentiment analysis... ({current} processed)"
                else:
                    message = f"Finalizing analysis... ({current} processed)"
                
                if task_manager and task_id:
                    task_manager.update_task_status(
                        task_id, TaskStatus.PROCESSING, overall_progress, message
                    )
        
        try:
            # 🔥 Use context-aware batch processing (from Dev version)
            analyses = await self.gemini_service.analyze_comments_batch_with_context(
                all_texts, post_context, gemini_progress_callback, objectives
            )
        except asyncio.CancelledError:
            logger.info(f"Processing cancelled for task {task_id}")
            if task_manager and task_id:
                task_manager.update_task_status(task_id, TaskStatus.CANCELLED, 0, "Processing cancelled by user")
            raise
        
        if task_manager and task_id:
            task_manager.update_task_status(
                task_id, TaskStatus.PROCESSING, 
                smooth_progress.get_smooth_progress('FINALIZING', 0.0),
                "Generating results..."
            )
        
        if progress_callback:
            progress_callback(90, 100)
        
        final_results = await self._create_final_results_enhanced(
            all_texts, analyses, metadata_df, client_id, base_filename, project, task_id, task_manager, post_context,
            objectives
        )
        
        if task_manager and task_id:
            task_manager.update_task_status(
                task_id, TaskStatus.PROCESSING, 
                smooth_progress.get_smooth_progress('FINALIZING', 0.8),
                "Creating Excel report..."
            )
        
        if progress_callback:
            progress_callback(100, 100)
        
        return final_results
    
    async def _create_final_results_enhanced(self, all_texts: List[str], analyses: List[Optional[Dict]],
                                           metadata_df: Optional[pd.DataFrame],
                                           client_id: str, base_filename: str, project: str = "default",
                                           task_id: str = None, task_manager=None,
                                           post_context: str = None, objectives: List[str] = ()) -> Dict[str, Any]:
        """Create final results with strict row filtering"""
        try:
            if task_manager and task_id and task_manager.is_task_cancelled(task_id):
                logger.info(f"Task {task_id} cancelled during result creation")
                raise asyncio.CancelledError("Task cancelled by user")
            
            valid_indices = []
            valid_rows = []
            translations = []
            sentiment_scores = []
            sentiment_list = []
            category_list = []
            objective_scores = []
            skipped_rows = 0
            
            self._log_processing_milestone("=== PROCESSING RESULTS WITH STRICT FILTERING ===", force_log=True)
            
            for idx, (text, analysis) in enumerate(zip(all_texts, analyses)):
                if analysis is None:
                    skipped_rows += 1
                    continue
                valid_indices.append(idx)
                valid_rows.append(text)
                translations.append(analysis["translation"])
                sentiment_scores.append(analysis["score"])
                sentiment_list.append(analysis["sentiment"].lower())
                category_list.append(analysis["category"])
                if objectives:
                    objective_scores.append(analysis["objectives"])
            
            self._processing_stats['total_processed'] += len(valid_rows)
            self._processing_stats['total_failed'] += skipped_rows
            
            self._log_processing_milestone("=== FILTERING COMPLETE ===", force_log=True)
            self._log_processing_milestone(f"✅ Successfully processed: {len(valid_rows)} rows", force_log=True)
            self._log_processing_milestone(f"❌ Skipped/Failed: {skipped_rows} rows", force_log=True)
            success_rate = (len(valid_rows)/(len(all_texts))*100) if all_texts else 0
            self._log_processing_milestone(f"📊 Success rate: {success_rate:.1f}%", force_log=True)
            
            if len(valid_rows) == 0:
                raise ValueError("No valid comments were successfully processed. All rows failed sentiment analysis.")
            
            if task_manager and task_id and task_manager.is_task_cancelled(task_id):
                logger.info(f"Task {task_id} cancelled during dataframe creation")
                raise asyncio.CancelledError("Task cancelled by user")
            
            processed_data = pd.DataFrame({
                "Text": valid_rows,
                "Translation": translations,
                "Sentiment Score": sentiment_scores,
                "Sentiment": sentiment_list,
                "Category": category_list
            })
            
            for k in range(len(objectives)):
                processed_data[f"Objective {k + 1} Stance"] = [s[k]["stance"] for s in objective_scores]
                processed_data[f"Objective {k + 1} Alignment"] = [s[k]["alignment"] for s in objective_scores]

            if settings.debug:
                logger.info(f"📋 Created base DataFrame with {len(processed_data)} rows and {len(processed_data.columns)} columns")
            
            if metadata_df is not None and len(metadata_df) > 0:
                valid_metadata = metadata_df.iloc[valid_indices].reset_index(drop=True)
                
                if len(valid_metadata) == len(processed_data):
                    for col in valid_metadata.columns:
                        # An input column named like an output column ("Sentiment") is kept, renamed.
                        name = col if col not in processed_data.columns else f"{col} (original)"
                        processed_data[name] = valid_metadata[col]
                    
                    if settings.debug:
                        logger.info(f"✅ Added metadata columns: {list(valid_metadata.columns)} for {len(valid_metadata)} rows")
                else:
                    logger.warning(f"⚠️ Metadata row count mismatch: {len(valid_metadata)} vs {len(processed_data)}")
            
            self._log_processing_milestone(f"📊 Sentiment breakdown: {dict(Counter(sentiment_list))}", force_log=True)

            if task_manager and task_id and task_manager.is_task_cancelled(task_id):
                logger.info(f"Task {task_id} cancelled before context generation")
                raise asyncio.CancelledError("Task cancelled by user")

            summaries = await self.gemini_service.summarize(
                [{"translation": t, "sentiment": s, "category": c}
                 for t, s, c in zip(translations, sentiment_list, category_list)],
                post_context or "",
            )
            positive_context, neutral_context, negative_context = (
                summaries["positive"], summaries["neutral"], summaries["negative"])

            objectives_summary = []
            if objectives:
                objective_summaries = await self.gemini_service.summarize_objectives(
                    objectives, [{"translation": t, "objectives": o} for t, o in zip(translations, objective_scores)])
                objectives_summary = objective_results(objectives, objective_scores, objective_summaries)

            sentiment_counts = dict(Counter(sentiment_list))
            category_counts = dict(Counter(category_list))
            
            # Wall-clock time plus a random suffix: loop.time() restarts at ~0
            # with every process, so names repeated and overwrote earlier results.
            new_filename = f"processed_{base_filename.replace('.xlsx', '')}_{int(time.time())}_{uuid.uuid4().hex[:6]}.xlsx"
            client_folder = os.path.join(UPLOAD_FOLDER, client_id)
            output_path = os.path.join(client_folder, new_filename)
            
            if task_manager and task_id and task_manager.is_task_cancelled(task_id):
                logger.info(f"Task {task_id} cancelled before Excel creation")
                raise asyncio.CancelledError("Task cancelled by user")
            
            loop = asyncio.get_event_loop()
            excel_created = await loop.run_in_executor(
                self.thread_pool,
                create_excel_with_charts_enhanced,
                processed_data, output_path, sentiment_counts, category_counts,
                positive_context, neutral_context, negative_context, summaries["overall"],
                objectives_summary
            )
            
            if not excel_created:
                raise ValueError("Failed to create Excel file")
            
            result_data = {
                "new_filename": new_filename,
                "client_id": client_id,
                "sentiment_counts": sentiment_counts,
                "category_counts": category_counts,
                "skipped_rows": skipped_rows,
                "total_comments": len(valid_rows),
                "processed_comments": len(valid_rows),
                "original_comments": len(all_texts),
                "success_rate": round((len(valid_rows)/len(all_texts))*100, 1),
                "overall_summary": summaries["overall"],
                "positive_context": positive_context,
                "neutral_context": neutral_context,
                "negative_context": negative_context,
                "objective_results": objectives_summary,
                "metadata_columns": list(processed_data.columns),
                "excel_row_count": len(processed_data)
            }
            
            self._log_processing_milestone("=== FINAL RESULTS SUMMARY ===", force_log=True)
            self._log_processing_milestone(f"📁 Excel file: {new_filename}", force_log=True)
            self._log_processing_milestone(f"📊 Rows in Excel: {len(processed_data)} (only successfully processed)", force_log=True)
            if settings.debug:
                logger.info(f"📋 Final columns: {list(processed_data.columns)}")
            self._log_processing_milestone(f"✅ Success rate: {result_data['success_rate']}%", force_log=True)

            # 🔥 ANALYTICS TRACKING FIX: Removed user_id from call
            try:
                if settings.debug:
                    logger.info(f"📊 Tracking analytics: project={project}, comments={len(valid_rows)}")
                
                simple_analytics.track_usage(
                    project=project or "default",
                    client_id=client_id,
                    comments_count=len(valid_rows),
                    operation_type="file_upload"
                )
                self._log_processing_milestone("✅ Analytics tracking successful", force_log=True)
            except Exception as e:
                logger.error(f"❌ Analytics tracking failed: {e}")
                
            return result_data
            
        except asyncio.CancelledError:
            logger.info(f"Result creation cancelled for task {task_id}")
            if task_manager and task_id:
                task_manager.update_task_status(task_id, TaskStatus.CANCELLED, 0, "Processing cancelled by user")
            raise
        except Exception as e:
            logger.error(f"Error creating final results: {str(e)}")
            raise
    
    # ... (These were not changed in the Dev version, so keeping them as is) ...
    
