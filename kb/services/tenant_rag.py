"""
Tenant-Specific RAG Service for Multi-Tenant WhatsApp Chatbot SaaS Platform

This service extends the existing RAG functionality to support tenant isolation,
ensuring that each tenant's knowledge base is kept completely separate.
"""

import json
import logging
from typing import Optional, Dict, Any, List, Tuple
from threading import Lock

logger = logging.getLogger("tenant_rag")

from backend.database_multi_tenant import (
    get_current_tenant_id, tenant_query, get_tenant_by_id
)


class TenantRAGService:
    """
    Service for managing tenant-specific knowledge bases and vector embeddings.
    
    Each tenant has their own isolated knowledge base with separate:
    - Document storage (knowledge_base table with tenant_id)
    - Vector embeddings (FAISS index with tenant-specific metadata)
    - Search results (filtered by tenant)
    """
    
    def __init__(self, tenant_id: int = None):
        """Initialize the RAG service for a specific tenant."""
        self.tenant_id = tenant_id or get_current_tenant_id()
        if not self.tenant_id:
            raise ValueError("tenant_id is required for TenantRAGService")
        
        # Tenant-specific FAISS index and metadata
        self._tenant_index = None
        self._tenant_ids = []
        self._tenant_metadata = []
        self._build_lock = Lock()
        
        # Load tenant configuration
        self._tenant_config = self._load_tenant_config()
    
    def _load_tenant_config(self) -> Dict[str, Any]:
        """Load configuration for this tenant."""
        tenant = get_tenant_by_id(self.tenant_id)
        if not tenant:
            raise ValueError(f"Tenant with ID {self.tenant_id} not found")
        
        return {
            'tenant_id': self.tenant_id,
            'company_name': tenant.get('company_name', ''),
            'industry_type': tenant.get('industry_type', 'general'),
            'system_prompt': tenant.get('system_prompt', '')
        }
    
    def _get_tenant_kb_entries(self) -> List[Dict[str, Any]]:
        """Get all knowledge base entries for this tenant."""
        return tenant_query('knowledge_base', self.tenant_id)
    
    def _get_tenant_faq_entries(self) -> List[Dict[str, Any]]:
        """Get all FAQ entries for this tenant."""
        return tenant_query('faq_dataset', self.tenant_id)
    
    def _get_tenant_cached_embeddings(self) -> List[Dict[str, Any]]:
        """Get all cached embeddings for this tenant."""
        return tenant_query('cached_embeddings', self.tenant_id)
    
    def build_tenant_index(self, force_rebuild: bool = False):
        """
        Build or rebuild the FAISS index for this tenant.
        
        This creates a tenant-specific vector index that contains only
        the documents belonging to this tenant.
        """
        if not force_rebuild and self._tenant_index is not None:
            logger.info(f"Tenant {self.tenant_id} index already built")
            return
        
        with self._build_lock:
            # Get all knowledge base entries for this tenant
            kb_entries = self._get_tenant_kb_entries()
            faq_entries = self._get_tenant_faq_entries()
            
            if not kb_entries and not faq_entries:
                logger.warning(f"No knowledge base entries found for tenant {self.tenant_id}")
                self._tenant_index = None
                self._tenant_ids = []
                self._tenant_metadata = []
                return
            
            # Combine entries
            all_entries = kb_entries + faq_entries
            
            # Extract text and metadata
            texts = []
            metadata_list = []
            ids = []
            
            for entry in all_entries:
                entry_id = entry.get('id')
                content = entry.get('content', '')
                
                # Skip empty entries
                if not content or not content.strip():
                    continue
                
                # Try to get chunks from entry
                chunks_json = entry.get('chunks_json')
                if chunks_json and isinstance(chunks_json, str):
                    try:
                        chunks = json.loads(chunks_json)
                        if isinstance(chunks, list):
                            for i, chunk in enumerate(chunks):
                                if chunk and chunk.strip():
                                    texts.append(chunk)
                                    metadata_list.append({
                                        'entry_id': entry_id,
                                        'chunk_index': i,
                                        'tenant_id': self.tenant_id,
                                        'source': entry.get('source', 'unknown'),
                                        'title': entry.get('title', 'Untitled'),
                                        'type': 'kb' if entry in kb_entries else 'faq'
                                    })
                                    ids.append(len(ids))
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Failed to parse chunks_json for entry {entry_id}")
                else:
                    # If no chunks, use the full content as a single chunk
                    texts.append(content)
                    metadata_list.append({
                        'entry_id': entry_id,
                        'chunk_index': 0,
                        'tenant_id': self.tenant_id,
                        'source': entry.get('source', 'unknown'),
                        'title': entry.get('title', 'Untitled'),
                        'type': 'kb' if entry in kb_entries else 'faq'
                    })
                    ids.append(len(ids))
            
            if not texts:
                logger.warning(f"No valid text content found for tenant {self.tenant_id}")
                self._tenant_index = None
                self._tenant_ids = []
                self._tenant_metadata = []
                return
            
            # Generate embeddings for all texts
            try:
                from .embeddings import get_embedding_model
                embedding_model = get_embedding_model()
                embeddings = embedding_model.encode(texts, show_progress_bar=False)
            except Exception as e:
                logger.error(f"Failed to generate embeddings for tenant {self.tenant_id}: {e}")
                self._tenant_index = None
                self._tenant_ids = []
                self._tenant_metadata = []
                return
            
            # Create FAISS index
            try:
                import faiss
                embedding_dim = embeddings.shape[1] if len(embeddings.shape) > 1 else 0
                
                if embedding_dim > 0:
                    self._tenant_index = faiss.IndexFlatL2(embedding_dim)
                    self._tenant_index.add(embeddings)
                    self._tenant_ids = ids
                    self._tenant_metadata = metadata_list
                    
                    logger.info(f"Built FAISS index for tenant {self.tenant_id}: {len(texts)} entries")
                else:
                    logger.error(f"Invalid embedding dimension: {embedding_dim}")
            except ImportError:
                logger.error("FAISS is not installed. Please install with: pip install faiss-cpu")
            except Exception as e:
                logger.error(f"Failed to create FAISS index for tenant {self.tenant_id}: {e}")
    
    def search_tenant_kb(self, query: str, k: int = 3) -> List[Dict[str, Any]]:
        """
        Search the tenant's knowledge base for relevant information.
        
        Args:
            query: The search query
            k: Number of results to return
            
        Returns:
            List of matching documents with metadata
        """
        if not self._tenant_index or not self._tenant_metadata:
            self.build_tenant_index()
        
        if not self._tenant_index:
            logger.warning(f"No FAISS index available for tenant {self.tenant_id}")
            return []
        
        try:
            # Get query embedding
            from .embeddings import get_embedding_model
            embedding_model = get_embedding_model()
            query_embedding = embedding_model.encode([query], show_progress_bar=False)
            
            # Search the index
            if len(query_embedding.shape) > 1 and query_embedding.shape[1] > 0:
                distances, indices = self._tenant_index.search(query_embedding, k)
            else:
                logger.error("Invalid query embedding shape")
                return []
            
            # Get results with metadata
            results = []
            for i, (distance, index) in enumerate(zip(distances[0], indices[0])):
                if 0 <= index < len(self._tenant_metadata):
                    metadata = self._tenant_metadata[index].copy()
                    metadata['distance'] = float(distance)
                    metadata['rank'] = i + 1
                    results.append(metadata)
            
            return results
            
        except Exception as e:
            logger.error(f"Search failed for tenant {self.tenant_id}: {e}")
            return []
    
    def get_tenant_answer(self, query: str) -> str:
        """
        Get the best answer to a query from the tenant's knowledge base.
        
        Args:
            query: The question or query
            
        Returns:
            The best matching text from the knowledge base
        """
        results = self.search_tenant_kb(query, k=3)
        
        if not results:
            return ""
        
        # Get the best result
        best_result = results[0]
        
        # Retrieve the actual text content
        try:
            with open('faq.db', 'r', encoding='utf-8') as db_file:
                pass  # This is a placeholder
            
            # Use the database to get the actual content
            entry_id = best_result.get('entry_id')
            chunk_index = best_result.get('chunk_index', 0)
            
            # Get the entry from the database
            entries = self._get_tenant_kb_entries()
            for entry in entries:
                if entry.get('id') == entry_id:
                    chunks_json = entry.get('chunks_json')
                    if chunks_json:
                        try:
                            chunks = json.loads(chunks_json)
                            if isinstance(chunks, list) and 0 <= chunk_index < len(chunks):
                                return chunks[chunk_index]
                        except (json.JSONDecodeError, TypeError):
                            pass
                    # Return the full content if no chunks
                    return entry.get('content', '')
            
            # If we can't find exact match, return first KB entry
            if entries:
                return entries[0].get('content', '')
            
        except Exception as e:
            logger.error(f"Failed to retrieve content for tenant {self.tenant_id}: {e}")
        
        return ""
    
    def add_tenant_document(self, title: str, content: str, source: str = None, 
                            category: str = None, tags: str = None) -> int:
        """
        Add a new document to the tenant's knowledge base.
        
        Args:
            title: Title of the document
            content: Text content of the document
            source: Source identifier
            category: Category for the document
            tags: Tags for the document
            
        Returns:
            ID of the created knowledge base entry
        """
        # Create chunks from the content
        chunks = self._chunk_content(content)
        
        # Save to database
        data = {
            'tenant_id': self.tenant_id,
            'title': title,
            'content': content,
            'source': source or 'tenant_upload',
            'category': category or 'general',
            'tags': tags,
            'chunks_json': json.dumps(chunks),
            'created_at': 'CURRENT_TIMESTAMP'
        }
        
        # Use direct SQL for now - in production use the tenant-specific create function
        from backend.database import get_db_context
        
        with get_db_context() as conn:
            cursor = conn.execute(
                """INSERT INTO knowledge_base 
                   (tenant_id, title, content, source, category, tags, chunks_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (self.tenant_id, title, content, source or 'tenant_upload', 
                 category or 'general', tags, json.dumps(chunks))
            )
            entry_id = cursor.lastrowid
        
        # Invalidate the current index
        self._tenant_index = None
        self._tenant_ids = []
        self._tenant_metadata = []
        
        logger.info(f"Added document '{title}' to tenant {self.tenant_id} knowledge base")
        
        return entry_id
    
    def add_tenant_faq(self, source_file: str, content: str, content_type: str = 'text',
                       page_number: int = 1) -> int:
        """
        Add an FAQ entry to the tenant's dataset.
        
        Args:
            source_file: Source file name
            content: Text content
            content_type: Type of content ('text', 'pdf', etc.)
            page_number: Page number for the content
            
        Returns:
            ID of the created FAQ entry
        """
        from backend.database import get_db_context
        
        with get_db_context() as conn:
            cursor = conn.execute(
                """INSERT INTO faq_dataset 
                   (tenant_id, source_file, content_type, content, page_number, created_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (self.tenant_id, source_file, content_type, content, page_number)
            )
            entry_id = cursor.lastrowid
        
        # Invalidate the current index
        self._tenant_index = None
        self._tenant_ids = []
        self._tenant_metadata = []
        
        logger.info(f"Added FAQ entry from '{source_file}' to tenant {self.tenant_id}")
        
        return entry_id
    
    def _chunk_content(self, content: str) -> List[str]:
        """Chunk content for better vector search."""
        from .rag import chunk_text
        return chunk_text(content)
    
    def clear_tenant_index(self):
        """Clear the tenant's FAISS index."""
        self._tenant_index = None
        self._tenant_ids = []
        self._tenant_metadata = []
        logger.info(f"Cleared FAISS index for tenant {self.tenant_id}")
    
    def remove_tenant_document(self, entry_id: int) -> bool:
        """Remove a document from the tenant's knowledge base."""
        from backend.database import get_db_context
        
        with get_db_context() as conn:
            cursor = conn.execute(
                "DELETE FROM knowledge_base WHERE id = ? AND tenant_id = ?",
                (entry_id, self.tenant_id)
            )
            deleted = cursor.rowcount > 0
        
        if deleted:
            # Invalidate the current index
            self.clear_tenant_index()
            logger.info(f"Removed document {entry_id} from tenant {self.tenant_id}")
        
        return deleted


# ── Global Tenant RAG Manager ───────────────────────────────────────────
# This manager keeps track of all tenant RAG services and provides easy access

class TenantRAGManager:
    """Manager for multiple tenant RAG services."""
    
    def __init__(self):
        self._tenant_services = {}
        self._lock = Lock()
    
    def get_tenant_service(self, tenant_id: int) -> TenantRAGService:
        """Get or create a RAG service for a specific tenant."""
        if tenant_id in self._tenant_services:
            return self._tenant_services[tenant_id]
        
        with self._lock:
            # Double-check after acquiring lock
            if tenant_id in self._tenant_services:
                return self._tenant_services[tenant_id]
            
            try:
                service = TenantRAGService(tenant_id)
                self._tenant_services[tenant_id] = service
                return service
            except ValueError:
                logger.error(f"Failed to create RAG service for tenant {tenant_id}")
                raise
    
    def search_all_tenants(self, query: str, k: int = 3) -> Dict[int, List[Dict[str, Any]]]:
        """
        Search across all tenant knowledge bases.
        
        This is typically not recommended due to data isolation concerns,
        but can be useful for global admin functions.
        
        Args:
            query: The search query
            k: Number of results per tenant
            
        Returns:
            Dictionary mapping tenant_id to search results
        """
        from backend.database_multi_tenant import list_tenants
        
        all_tenants = list_tenants(limit=100)  # Limit to active tenants
        results = {}
        
        for tenant in all_tenants:
            tenant_id = tenant['id']
            try:
                service = self.get_tenant_service(tenant_id)
                tenant_results = service.search_tenant_kb(query, k)
                if tenant_results:
                    results[tenant_id] = tenant_results
            except Exception as e:
                logger.error(f"Search failed for tenant {tenant_id}: {e}")
        
        return results


# ── Global Instance ──────────────────────────────────────────────────────
# Create a global manager instance
rag_manager = TenantRAGManager()


# ── Convenience Functions ─────────────────────────────────────────────────

def search_tenant_kb(tenant_id: int, query: str, k: int = 3) -> List[Dict[str, Any]]:
    """
    Convenience function to search a tenant's knowledge base.
    
    Args:
        tenant_id: The tenant ID to search
        query: The search query
        k: Number of results to return
        
    Returns:
        List of matching documents with metadata
    """
    return rag_manager.get_tenant_service(tenant_id).search_tenant_kb(query, k)


def get_tenant_answer(tenant_id: int, query: str) -> str:
    """
    Convenience function to get an answer from a tenant's knowledge base.
    
    Args:
        tenant_id: The tenant ID to search
        query: The search query
        
    Returns:
        The best matching text from the knowledge base
    """
    return rag_manager.get_tenant_service(tenant_id).get_tenant_answer(query)


def add_document_to_tenant(tenant_id: int, title: str, content: str, 
                        source: str = None, category: str = None) -> int:
    """
    Convenience function to add a document to a tenant's knowledge base.
    
    Args:
        tenant_id: The tenant ID
        title: Document title
        content: Document content
        source: Source identifier
        category: Content category
        
    Returns:
        ID of the created knowledge base entry
    """
    return rag_manager.get_tenant_service(tenant_id).add_tenant_document(
        title, content, source, category
    )


def rebuild_tenant_index(tenant_id: int):
    """Rebuild the FAISS index for a specific tenant."""
    return rag_manager.get_tenant_service(tenant_id).build_tenant_index(force_rebuild=True)


# ── Async Compatibility ─────────────────────────────────────────────────

async def async_search_tenant_kb(tenant_id: int, query: str, k: int = 3) -> List[Dict[str, Any]]:
    """Async version of tenant KB search."""
    return search_tenant_kb(tenant_id, query, k)


async def async_get_tenant_answer(tenant_id: int, query: str) -> str:
    """Async version of tenant answer retrieval."""
    return get_tenant_answer(tenant_id, query)