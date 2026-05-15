"""
Advanced text chunking service.
Handles large documents (1000+ pages) with semantic boundaries, section detection,
smart overlap, and configurable chunk size — optimised for RAG retrieval quality.
"""
import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_CHUNK_SIZE    = 1200   # characters; ~250-300 tokens for BGE models
DEFAULT_CHUNK_OVERLAP = 200    # characters overlap between consecutive chunks
MIN_CHUNK_LEN         = 60    # skip chunks shorter than this
EMBED_BATCH_SIZE      = 64    # embeddings generated in batches of this size

# ── Section-header patterns ───────────────────────────────────────────────────
_SECTION_RE = re.compile(
    r"""
    (?:^|\n)
    (
        # Numbered heading: "1.", "1.1", "Chapter 3", "Section 2.4"
        (?:Chapter|Section|Part|Unit|Module|Lecture|Topic)\s+[\d\w]+[\.\s]
        |
        (?:\d+\.)+\d*\s+[A-Z]
        |
        # ALL-CAPS line ≥ 4 chars
        (?:[A-Z][A-Z\s\d\-,:]{3,})\n
        |
        # Markdown-style heading
        #{1,4}\s+\S
    )
    """,
    re.VERBOSE | re.MULTILINE,
)

_SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+')
_WHITESPACE_RE   = re.compile(r'\s{3,}')


class TextChunker:
    """
    Multi-strategy text chunker for large documents.

    Strategy priority (for every paragraph block):
      1. Respect natural section headings.
      2. Split on paragraph boundaries.
      3. Fall back to sentence splitting.
      4. Hard-split on characters only as last resort.
    Each chunk carries rich metadata for better RAG retrieval.
    """

    def __init__(
        self,
        chunk_size:    int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        min_chunk_len: int = MIN_CHUNK_LEN,
    ):
        self.chunk_size    = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_len = min_chunk_len
        logger.info(
            f"TextChunker ready — chunk_size={chunk_size}, "
            f"overlap={chunk_overlap}, min_len={min_chunk_len}"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """Simple overlap-based chunking (kept for backward-compat)."""
        return await self.chunk_text_semantic(text)

    async def chunk_text_semantic(
        self,
        text: str,
        source_meta: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Full semantic chunking pipeline.
        Returns list of chunk dicts with text + metadata.
        Progress-friendly: yields fine-grained sub-steps that the caller
        can use to update a progress bar.
        """
        if not text or not text.strip():
            return []

        # 1. Normalize whitespace
        text = _WHITESPACE_RE.sub(' ', text)
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # 2. Split into sections first, then paragraphs
        raw_blocks = self._split_sections(text)

        # 3. Build chunks with overlap from those blocks
        chunks = self._blocks_to_chunks(raw_blocks)

        # 4. Enrich with metadata
        result: List[Dict[str, Any]] = []
        for i, (chunk_text, chunk_meta) in enumerate(chunks):
            if len(chunk_text.strip()) < self.min_chunk_len:
                continue
            entry: Dict[str, Any] = {
                "chunk_index": i,
                "text": chunk_text.strip(),
                "char_count": len(chunk_text),
                "chunk_type": chunk_meta.get("type", "paragraph"),
            }
            if source_meta:
                entry["metadata"] = {**source_meta, **chunk_meta}
            else:
                entry["metadata"] = chunk_meta
            result.append(entry)

        # Re-index after filtering
        for i, chunk in enumerate(result):
            chunk["chunk_index"] = i

        logger.info(f"Chunker produced {len(result)} chunks from {len(text)} chars")
        return result

    async def chunk_text_with_progress(
        self,
        text: str,
        progress_callback=None,   # async callable(pct: int, stage: str)
        source_meta: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Same as chunk_text_semantic but emits progress callbacks so the
        document processor can update the DB progress field in real-time.
        """
        if progress_callback:
            await progress_callback(5, "parsing text structure")

        if not text or not text.strip():
            return []

        text = _WHITESPACE_RE.sub(' ', text)
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        if progress_callback:
            await progress_callback(10, "splitting sections")

        raw_blocks = self._split_sections(text)

        if progress_callback:
            await progress_callback(20, "building chunks")

        chunks = self._blocks_to_chunks(raw_blocks)

        if progress_callback:
            await progress_callback(30, "enriching metadata")

        result: List[Dict[str, Any]] = []
        total = len(chunks)
        for i, (chunk_text, chunk_meta) in enumerate(chunks):
            if len(chunk_text.strip()) < self.min_chunk_len:
                continue
            entry: Dict[str, Any] = {
                "chunk_index": i,
                "text": chunk_text.strip(),
                "char_count": len(chunk_text),
                "chunk_type": chunk_meta.get("type", "paragraph"),
            }
            if source_meta:
                entry["metadata"] = {**source_meta, **chunk_meta}
            else:
                entry["metadata"] = chunk_meta
            result.append(entry)

            # Emit progress every 10% of chunks
            if progress_callback and total > 0 and i % max(1, total // 10) == 0:
                pct = 30 + int((i / total) * 20)  # 30-50% range
                await progress_callback(pct, f"chunked {i+1}/{total} blocks")

        for i, chunk in enumerate(result):
            chunk["chunk_index"] = i

        if progress_callback:
            await progress_callback(50, "chunking complete")

        logger.info(f"Chunker produced {len(result)} chunks")
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _split_sections(self, text: str) -> List[tuple]:
        """
        Split text into (block_text, meta) pairs, respecting section headings.
        Each pair has a 'type' key: 'section_heading', 'paragraph', or 'list'.
        """
        blocks: List[tuple] = []
        pos = 0
        for match in _SECTION_RE.finditer(text):
            before = text[pos:match.start()].strip()
            if before:
                blocks.extend(self._split_paragraphs(before))
            heading = match.group(0).strip()
            blocks.append((heading, {"type": "section_heading"}))
            pos = match.end()

        remaining = text[pos:].strip()
        if remaining:
            blocks.extend(self._split_paragraphs(remaining))

        return blocks

    def _split_paragraphs(self, text: str) -> List[tuple]:
        """Split a text block on double-newlines into paragraph chunks."""
        parts = re.split(r'\n{2,}', text)
        blocks: List[tuple] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Detect list items
            chunk_type = "list" if re.match(r'^[\s]*[-*•◦▪]\s', part, re.MULTILINE) else "paragraph"
            blocks.append((part, {"type": chunk_type}))
        return blocks

    def _blocks_to_chunks(self, blocks: List[tuple]) -> List[tuple]:
        """
        Merge blocks into final chunks respecting max chunk_size with overlap.
        Returns list of (text, meta) tuples.
        """
        chunks: List[tuple] = []
        buffer     = ""
        buffer_meta: Dict[str, Any] = {}

        def flush_buffer():
            nonlocal buffer, buffer_meta
            if buffer.strip():
                for ch in self._split_if_too_long(buffer.strip(), buffer_meta):
                    chunks.append(ch)
            buffer = ""
            buffer_meta = {}

        for block_text, block_meta in blocks:
            # Section headings always get their own chunk (they anchor retrieval)
            if block_meta.get("type") == "section_heading":
                flush_buffer()
                chunks.append((block_text, block_meta))
                # Include heading in next chunk for context
                buffer = block_text + "\n"
                buffer_meta = {"type": "paragraph"}
                continue

            candidate = buffer + ("\n\n" if buffer else "") + block_text
            if len(candidate) <= self.chunk_size:
                buffer = candidate
                buffer_meta = block_meta
            else:
                flush_buffer()
                buffer = block_text
                buffer_meta = block_meta

        flush_buffer()
        return self._add_overlap(chunks)

    def _split_if_too_long(self, text: str, meta: Dict[str, Any]) -> List[tuple]:
        """If text > chunk_size, split on sentences then hard-split."""
        if len(text) <= self.chunk_size:
            return [(text, meta)]

        # Try sentence splitting
        sentences = _SENTENCE_END_RE.split(text)
        result: List[tuple] = []
        current = ""
        for sent in sentences:
            candidate = current + " " + sent if current else sent
            if len(candidate) <= self.chunk_size:
                current = candidate
            else:
                if current:
                    result.append((current.strip(), meta))
                # Hard-split if a single sentence exceeds limit
                if len(sent) > self.chunk_size:
                    result.extend(self._hard_split(sent, meta))
                    current = ""
                else:
                    current = sent
        if current:
            result.append((current.strip(), meta))
        return result if result else [(text[:self.chunk_size], meta)]

    def _hard_split(self, text: str, meta: Dict[str, Any]) -> List[tuple]:
        """Last-resort hard split on character boundary."""
        result: List[tuple] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            result.append((text[start:end].strip(), {**meta, "type": "hard_split"}))
            start = end - self.chunk_overlap
        return result

    def _add_overlap(self, chunks: List[tuple]) -> List[tuple]:
        """
        Add trailing-overlap: prefix each chunk (except the first) with
        the last `chunk_overlap` chars of the previous chunk.
        This improves retrieval continuity across chunk boundaries.
        """
        if len(chunks) <= 1:
            return chunks
        result: List[tuple] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_text, _      = chunks[i - 1]
            curr_text, curr_meta = chunks[i]
            overlap = prev_text[-self.chunk_overlap:].strip() if len(prev_text) > self.chunk_overlap else ""
            if overlap and not curr_text.startswith(overlap):
                curr_text = overlap + " … " + curr_text
            result.append((curr_text, curr_meta))
        return result


# ── Singleton ──────────────────────────────────────────────────────────────────
_chunker: Optional[TextChunker] = None


def get_chunker(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> TextChunker:
    """Return the global TextChunker singleton (lazy init)."""
    global _chunker
    if _chunker is None:
        _chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return _chunker
