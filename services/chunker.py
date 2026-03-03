"""
Text chunking service for document processing
"""
import logging
from typing import List, Dict, Any
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class TextChunker:
    """Service for chunking text into manageable pieces"""
    
    def __init__(self):
        """Initialize text chunker"""
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        logger.info("✅ Text chunker initialized")
    
    async def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """Chunk text into overlapping segments"""
        try:
            if not text or not text.strip():
                return []
            
            # Simple chunking by character count
            chunks = []
            start = 0
            chunk_index = 0
            
            while start < len(text):
                end = start + self.chunk_size
                chunk_text = text[start:end]
                
                # Try to break at sentence boundary
                if end < len(text):
                    last_period = chunk_text.rfind('.')
                    last_newline = chunk_text.rfind('\n')
                    break_point = max(last_period, last_newline)
                    
                    if break_point > start + self.chunk_size // 2:
                        chunk_text = text[start:start + break_point + 1]
                        end = start + break_point + 1
                
                chunks.append({
                    "text": chunk_text.strip(),
                    "chunk_index": chunk_index,
                    "start_char": start,
                    "end_char": end
                })
                
                # Move start position with overlap
                start = end - self.chunk_overlap
                chunk_index += 1
            
            logger.info(f"Created {len(chunks)} chunks from text of length {len(text)}")
            return chunks
            
        except Exception as e:
            logger.error(f"Error chunking text: {e}")
            return []
    
    async def chunk_text_semantic(self, text: str) -> List[Dict[str, Any]]:
        """Chunk text using semantic boundaries (paragraphs, sections)"""
        try:
            if not text or not text.strip():
                return []
            
            # Split by paragraphs first
            paragraphs = text.split('\n\n')
            chunks = []
            chunk_index = 0
            
            for paragraph in paragraphs:
                paragraph = paragraph.strip()
                if not paragraph:
                    continue
                
                # If paragraph is too long, split it further
                if len(paragraph) > self.chunk_size:
                    sub_chunks = await self.chunk_text(paragraph)
                    for sub_chunk in sub_chunks:
                        sub_chunk["chunk_index"] = chunk_index
                        sub_chunk["chunk_type"] = "paragraph"
                        chunks.append(sub_chunk)
                        chunk_index += 1
                else:
                    chunks.append({
                        "text": paragraph,
                        "chunk_index": chunk_index,
                        "chunk_type": "paragraph"
                    })
                    chunk_index += 1
            
            logger.info(f"Created {len(chunks)} semantic chunks")
            return chunks
            
        except Exception as e:
            logger.error(f"Error in semantic chunking: {e}")
            return []


# Global instance
text_chunker = TextChunker()


def get_chunker() -> TextChunker:
    """Get text chunker instance"""
    return text_chunker
