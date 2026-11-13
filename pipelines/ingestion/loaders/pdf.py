# pipelines/ingestion/loaders/pdf.py
import base64
import logging
import os
import re
import tempfile
from typing import Any, Dict, List, Tuple

from unstructured.partition.pdf import partition_pdf

logger = logging.getLogger(__name__)


def _html_table_to_markdown(html: str) -> str:
    """Convert an HTML table to a simple Markdown table for better embedding quality."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        rows = []
        for tr in soup.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            rows.append("| " + " | ".join(cells) + " |")
        if len(rows) >= 1:
            # Add header separator after first row
            col_count = rows[0].count("|") - 1
            rows.insert(1, "| " + " | ".join(["---"] * col_count) + " |")
        return "\n".join(rows)
    except Exception:
        # Fallback: strip HTML tags
        return re.sub(r"<[^>]+>", " ", html).strip()


def parse_pdf_bytes(
    file_bytes: bytes, filename: str, extract_images: bool = False
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Parses a PDF file stream using a temporary file for memory efficiency.
    Extracts text, table structure, and optionally images.

    Args:
        file_bytes: The raw bytes of the PDF file.
        filename: Original filename for metadata.
        extract_images: If True, extract embedded images from the PDF.

    Returns:
        Tuple containing (extracted_text_content, metadata_dict, images_list)
    """
    text_content = ""
    tables = []
    images: List[Dict[str, Any]] = []

    # Use a temporary file on disk (EBS/Ephemeral storage)
    # instead of processing entirely in RAM (BytesIO).
    # This is critical for preventing OOM kills on K8s workers with large PDFs.
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp_file:
        try:
            # 1. Write bytes to disk
            tmp_file.write(file_bytes)
            tmp_file.flush()

            # 2. Partition PDF
            # INGEST_PDF_STRATEGY (default "hi_res"): "hi_res" uses OCR (Tesseract) and layout analysis (Detectron2/ONNX) and
            # needs those system packages and model weights; "fast" extracts the text layer with pdfminer only (no OCR, no
            # models, no table structure), which is what a stock CPU Ray image can run. Scanned PDFs need "hi_res".
            strategy = os.getenv("INGEST_PDF_STRATEGY", "hi_res").strip().lower()
            if strategy not in {"hi_res", "fast"}:
                raise ValueError(f"INGEST_PDF_STRATEGY must be 'hi_res' or 'fast', got {strategy!r}")
            partition_kwargs = dict(
                filename=tmp_file.name,
                strategy=strategy,
                include_page_breaks=True,
            )
            if strategy == "hi_res":
                partition_kwargs["infer_table_structure"] = True
            if extract_images:
                partition_kwargs["extract_images_in_pdf"] = True

            elements = partition_pdf(**partition_kwargs)

            # 3. Process Elements
            for el in elements:
                page_num = getattr(el.metadata, "page_number", 0) or 0

                if el.category == "Table":
                    # Convert table HTML to Markdown for better embedding quality
                    if hasattr(el.metadata, "text_as_html") and el.metadata.text_as_html:
                        md_table = _html_table_to_markdown(el.metadata.text_as_html)
                        text_content += md_table + "\n\n"
                        tables.append(el.metadata.text_as_html)
                    else:
                        text_content += str(el) + "\n"

                elif el.category == "Image" and extract_images:
                    # Extract image data if available
                    image_data = None
                    mime_type = "image/png"

                    if hasattr(el.metadata, "image_base64") and el.metadata.image_base64:
                        image_data = base64.b64decode(el.metadata.image_base64)
                        if hasattr(el.metadata, "image_mime_type"):
                            mime_type = el.metadata.image_mime_type

                    if image_data:
                        # Check size limit
                        max_bytes = int(os.getenv("MAX_IMAGE_SIZE_MB", "10")) * 1024 * 1024
                        if len(image_data) <= max_bytes:
                            images.append({
                                "image_bytes": image_data,
                                "mime_type": mime_type,
                                "page": page_num,
                                "description": str(el).strip() if str(el).strip() else "",
                                "source_type": "pdf_extract",
                            })
                        else:
                            logger.warning(
                                f"Skipping large image ({len(image_data)} bytes) "
                                f"from {filename} page {page_num}"
                            )

                    # Also include any caption/OCR text
                    el_text = str(el).strip()
                    if el_text:
                        text_content += el_text + "\n"
                else:
                    text_content += str(el) + "\n"

        except Exception as e:
            logger.error(f"Failed to parse PDF {filename}: {str(e)}")
            raise e

    # 4. Construct Metadata
    metadata = {
        "filename": filename,
        "type": "pdf",
        "has_tables": len(tables) > 0,
        "table_count": len(tables),
        "image_count": len(images),
    }

    return text_content, metadata, images
