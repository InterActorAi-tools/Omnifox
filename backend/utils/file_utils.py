"""
Enhanced file utility functions for Omnifox with metadata support
"""
import io
import os
import pandas as pd
import logging
from typing import Dict, Any, List

from utils.crypto import read_file, write_file

logger = logging.getLogger(__name__)

def read_and_clean_excel_enhanced(file_path: str) -> Dict[str, Any]:
    """Read and clean Excel file with metadata preservation"""
    try:
        if not os.path.exists(file_path):
            raise ValueError("The uploaded file could not be found. Please upload it again.")
        
        # Cells as written: "NA", "None" or "007" are data, not missing values or numbers.
        df = pd.read_excel(io.BytesIO(read_file(file_path)), keep_default_na=False, na_values=[""], dtype=object)

        if 'Text' not in df.columns:
            raise ValueError(f"Required 'Text' column not found. Available columns: {list(df.columns)}")
        
        # Clean data - remove NaN values and empty strings from Text column
        df.dropna(subset=['Text'], inplace=True)
        df = df[df['Text'].astype(str).str.strip() != '']
        
        if len(df) == 0:
            raise ValueError("No valid text found in the uploaded file after filtering empty rows")
        
        # Extract texts
        all_texts = df['Text'].astype(str).tolist()
        
        # Preserve metadata columns (everything except Text)
        metadata_columns = [col for col in df.columns if col != 'Text']
        metadata_df = None
        
        if metadata_columns:
            metadata_df = df[metadata_columns].copy()
            logger.info(f"Preserved metadata columns: {metadata_columns}")
        
        logger.info(f"Successfully read {len(all_texts)} valid text entries with metadata")
        
        return {
            'texts': all_texts,
            'metadata_df': metadata_df,
            'original_df': df,
            'metadata_columns': metadata_columns
        }
        
    except Exception as e:
        logger.error(f"Error reading Excel file: {str(e)}")
        raise ValueError(f"Error processing Excel file: {str(e)}")

def create_excel_with_charts_enhanced(processed_data: pd.DataFrame, output_path: str, 
                                    sentiment_counts: Dict[str, int], category_counts: Dict[str, int],
                                    positive_context: str, neutral_context: str, negative_context: str,
                                    overall_summary: str = "", objective_results: List[Dict] = ()) -> bool:
    """Create Excel file with charts, data, and preserved metadata"""
    try:
        # 🔥 CRITICAL VALIDATION: Ensure we only have valid sentiment data
        if len(processed_data) == 0:
            logger.error("❌ No data to write to Excel file")
            return False

        # 🔥 VALIDATE sentiment values are only valid ones
        valid_sentiments = {'positive', 'negative', 'neutral'}
        invalid_sentiments = set(processed_data['Sentiment'].str.lower()) - valid_sentiments
        if invalid_sentiments:
            logger.warning(f"⚠️ Found invalid sentiments: {invalid_sentiments}")
            # Remove rows with invalid sentiments
            original_count = len(processed_data)
            processed_data = processed_data[processed_data['Sentiment'].str.lower().isin(valid_sentiments)]
            filtered_count = len(processed_data)
            logger.info(f"🔄 Filtered out invalid sentiments: {original_count} → {filtered_count} rows")
            
            if len(processed_data) == 0:
                logger.error("❌ No valid sentiment data remaining after filtering")
                return False

        # Comments are untrusted text: never let "=..." become a live formula.
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter", engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}}) as writer:
            # Write the main data (now includes metadata columns and is fully validated)
            processed_data.to_excel(writer, index=False, sheet_name="Processed Data")
            
            # Get workbook and worksheet objects
            workbook = writer.book
            worksheet = writer.sheets["Processed Data"]
            
            # Determine the starting column for charts (after data columns)
            data_col_count = len(processed_data.columns)
            chart_start_col = max(12, data_col_count + 2)  # Start at column L or after data columns
            
            # Convert column number to Excel letter
            def col_num_to_letter(col_num):
                result = ""
                while col_num > 0:
                    col_num -= 1
                    result = chr(65 + col_num % 26) + result
                    col_num //= 26
                return result
            
            chart_col_letter = col_num_to_letter(chart_start_col)
            
            # Write chart data for sentiment
            final_sentiment_counts = processed_data['Sentiment'].str.lower().value_counts().to_dict()
            final_category_counts = processed_data['Category'].value_counts().to_dict()

            logger.info(f"📊 Final sentiment counts: {final_sentiment_counts}")

            # Write chart data for sentiment
            worksheet.write_row(f"{chart_col_letter}1", ["Sentiment", "Count"])
            row_index = 2
            for key, value in final_sentiment_counts.items():
                worksheet.write_row(f"{chart_col_letter}{row_index}", [key.capitalize(), value])
                row_index += 1
            
            # Write chart data for category
            worksheet.write_row(f"{chart_col_letter}10", ["Category", "Count"])
            row_index = 11
            for key, value in final_category_counts.items():
                worksheet.write_row(f"{chart_col_letter}{row_index}", [key, value])
                row_index += 1
            
            # Write sentiment contexts
            next_col_letter = col_num_to_letter(chart_start_col + 3)
            worksheet.write_row(f"{next_col_letter}1", ["Positive Sentiment Context"])
            worksheet.write_row(f"{next_col_letter}2", [positive_context])
            worksheet.write_row(f"{next_col_letter}4", ["Neutral Sentiment Context"])
            worksheet.write_row(f"{next_col_letter}5", [neutral_context])
            worksheet.write_row(f"{next_col_letter}7", ["Negative Sentiment Context"])
            worksheet.write_row(f"{next_col_letter}8", [negative_context])
            worksheet.write_row(f"{next_col_letter}10", ["Overall Summary"])
            worksheet.write_row(f"{next_col_letter}11", [overall_summary])
            
            # Create sentiment pie chart
            chart1 = workbook.add_chart({"type": "pie"})
            sentiment_end_row = len(sentiment_counts) + 1
            chart1.add_series({
                "name": "Sentiment Breakdown",
                "categories": f"'Processed Data'!${chart_col_letter}$2:${chart_col_letter}${sentiment_end_row}",
                "values": f"'Processed Data'!${col_num_to_letter(chart_start_col + 1)}$2:${col_num_to_letter(chart_start_col + 1)}${sentiment_end_row}",
                "data_labels": {"percentage": True, "category": True}
            })
            chart1.set_title({"name": "Sentiment Breakdown"})
            chart1.set_size({"width": 480, "height": 288})
            worksheet.insert_chart(f"{next_col_letter}10", chart1)
            
            # Create category pie chart
            chart2 = workbook.add_chart({"type": "pie"})
            category_end_row = len(category_counts) + 10
            chart2.add_series({
                "name": "Category Breakdown",
                "categories": f"'Processed Data'!${chart_col_letter}$11:${chart_col_letter}${category_end_row}",
                "values": f"'Processed Data'!${col_num_to_letter(chart_start_col + 1)}$11:${col_num_to_letter(chart_start_col + 1)}${category_end_row}",
                "data_labels": {"percentage": True, "category": True}
            })
            chart2.set_title({"name": "Category Breakdown"})
            chart2.set_size({"width": 480, "height": 288})
            worksheet.insert_chart(f"{next_col_letter}26", chart2)
            
            # Format the worksheet
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'fg_color': '#D7E4BC',
                'border': 1
            })
            
            # Apply header formatting
            for col_num, value in enumerate(processed_data.columns.values):
                worksheet.write(0, col_num, value, header_format)
            
            # Auto-adjust column widths with better handling for metadata columns
            for i, col in enumerate(processed_data.columns):
                if col in ['Name', 'Time']:
                    # Special handling for metadata columns
                    max_length = min(max(
                        processed_data[col].astype(str).map(len).max(),
                        len(col)
                    ) + 2, 30)  # Cap at 30 for readability
                elif col in ['Likes', 'Replies']:
                    # Numeric columns can be smaller
                    max_length = max(len(col) + 2, 8)
                else:
                    # Text and other columns
                    max_length = min(max(
                        processed_data[col].astype(str).map(len).max(),
                        len(col)
                    ) + 2, 50)
                
                worksheet.set_column(i, i, max_length)

            if objective_results:
                pd.DataFrame([{
                    "Objective": r["objective"],
                    "Relevant Comments": r["relevant_comments"],
                    "Supports": r["supports"],
                    "Neutral": r["neutral"],
                    "Against": r["against"],
                    "% Met": r["percent_met"],
                    "Average Alignment": r["average_alignment"],
                    "Summary": r["summary"],
                } for r in objective_results]).to_excel(writer, index=False, sheet_name="Objectives")
                writer.sheets["Objectives"].set_column(0, 0, 50)
                writer.sheets["Objectives"].set_column(7, 7, 100)
        
        write_file(output_path, buffer.getvalue())
        logger.info("Successfully created enhanced Excel file with metadata")
        return True
        
    except Exception as e:
        logger.error(f"Error creating enhanced Excel file: {e}")
        return False

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe file system usage. ASCII only: upload paths
    are validated against [A-Za-z0-9._@+-], so an Arabic or accented name
    becomes "file.xlsx" instead of being rejected."""
    import re

    stem, ext = os.path.splitext(filename)
    stem = re.sub(r'_+', '_', re.sub(r'[^A-Za-z0-9\-_.]', '_', stem)).strip('_.')
    ext = re.sub(r'[^A-Za-z0-9.]', '', ext)
    return (stem or 'file') + ext

