"""
ADVANCED RAG - Vector Search with LlamaIndex and Qdrant
=====================================================
Upgraded version of simple_rag.py featuring:
- Qdrant local vector database
- LlamaIndex document management
- Local embedding models
- File indexing support

Maintains compatibility with the original SimpleRAG and ChimeraKnowledgeBase
class interfaces for seamless integration with CHIMERA Ultimate.
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import Path

# Try imports, fallback to simple implementation if not available
try:
    from llama_index.core import (
        VectorStoreIndex, 
        SimpleDirectoryReader, 
        StorageContext, 
        Document as LlamaDocument,
        ServiceContext,
        set_global_service_context
    )
    from llama_index.vector_stores.qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient
    from llama_index.embeddings.openai import OpenAIEmbedding
    # For local embeddings (requires llama-index-embeddings-huggingface)
    # from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    
    LLAMA_INDEX_AVAILABLE = True
except ImportError:
    LLAMA_INDEX_AVAILABLE = False


# Original Document class for compatibility
from dataclasses import dataclass
@dataclass
class Document:
    """Simple document representation for compatibility"""
    text: str
    metadata: dict = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class AdvancedRAG:
    """
    Advanced RAG implementation using LlamaIndex and Qdrant
    """
    
    def __init__(self, collection_name: str = "chimera_knowledge"):
        self.collection_name = collection_name
        self.documents: List[Document] = []
        
        if LLAMA_INDEX_AVAILABLE:
            # Initialize Qdrant client (local mode)
            self.client = QdrantClient(path="./qdrant_db")
            
            # Initialize vector store
            self.vector_store = QdrantVectorStore(
                client=self.client, 
                collection_name=collection_name
            )
            
            self.storage_context = StorageContext.from_defaults(
                vector_store=self.vector_store
            )
            
            # Initial index (empty or loaded from storage)
            try:
                self.index = VectorStoreIndex.from_vector_store(
                    self.vector_store,
                    storage_context=self.storage_context
                )
            except:
                self.index = None
        else:
            # Fallback to simple RAG behavior if LlamaIndex not available
            self.index = None

    def add_documents(self, documents: List[Document]):
        """Add documents to the knowledge base"""
        for doc in documents:
            self.documents.append(doc)
            
        if LLAMA_INDEX_AVAILABLE:
            # Convert to LlamaIndex documents
            llama_docs = [
                LlamaDocument(text=d.text, extra_info=d.metadata) 
                for d in documents
            ]
            
            if self.index is None:
                self.index = VectorStoreIndex.from_documents(
                    llama_docs,
                    storage_context=self.storage_context
                )
            else:
                for l_doc in llama_docs:
                    self.index.insert(l_doc)
        else:
            print("Warning: LlamaIndex not available. Documents added to memory only.")

    def add_file(self, file_path: str):
        """Index a local file into the RAG system"""
        if not LLAMA_INDEX_AVAILABLE:
            print("⚠️ LlamaIndex required for file indexing.")
            return False
            
        try:
            reader = SimpleDirectoryReader(input_files=[file_path])
            documents = reader.load_data()
            
            if self.index is None:
                self.index = VectorStoreIndex.from_documents(
                    documents,
                    storage_context=self.storage_context
                )
            else:
                for doc in documents:
                    self.index.insert(doc)
            return True
        except Exception as e:
            print(f"Error indexing file: {e}")
            return False

    def retrieve(
        self, 
        query: str, 
        top_k: int = 3,
        min_score: float = 0.1
    ) -> List[Document]:
        """Retrieve most relevant documents"""
        if not LLAMA_INDEX_AVAILABLE or self.index is None:
            # Fallback to empty list or simple search if needed
            return []
            
        try:
            retriever = self.index.as_retriever(similarity_top_k=top_k)
            nodes = retriever.retrieve(query)
            
            results = []
            for node in nodes:
                results.append(Document(
                    text=node.node.get_content(),
                    metadata=node.node.metadata
                ))
            return results
        except Exception as e:
            print(f"Retrieval error: {e}")
            return []

    def query(
        self, 
        query: str, 
        llm_callable=None,
        top_k: int = 3
    ) -> str:
        """Full RAG query: retrieve + augment + generate"""
        if not LLAMA_INDEX_AVAILABLE or self.index is None:
            return "RAG system not initialized."
            
        try:
            query_engine = self.index.as_query_engine(similarity_top_k=top_k)
            response = query_engine.query(query)
            return str(response)
        except Exception as e:
            return f"Query error: {e}"

    def get_status(self) -> dict:
        """Get RAG status"""
        return {
            "documents": len(self.documents),
            "vector_store": "Qdrant (Local)" if LLAMA_INDEX_AVAILABLE else "Memory",
            "collection": self.collection_name,
            "status": "Ready" if self.index else "Empty"
        }


class AdvancedChimeraKnowledgeBase(AdvancedRAG):
    """
    Pre-populated advanced knowledge base for CHIMERA
    """
    
    def __init__(self):
        super().__init__(collection_name="chimera_core")
        self._load_default_knowledge()
        
    def _load_default_knowledge(self):
        """Load default knowledge base from original simple_rag.py"""
        docs = [
            Document(
                text="CHIMERA is a multi-model LLM system that uses consensus voting to determine the best response. It combines local models with cloud APIs for robust responses.",
                metadata={"topic": "chimera", "type": "architecture"}
            ),
            Document(
                text="Quantum computing uses qubits that can exist in superposition (multiple states) and entanglement (correlated states). This allows quantum algorithms to explore many solutions simultaneously.",
                metadata={"topic": "quantum", "type": "concept"}
            ),
            Document(
                text="Token optimization reduces API costs by compressing prompts, removing filler words, and summarizing conversation history while preserving key information.",
                metadata={"topic": "tokens", "type": "optimization"}
            ),
            Document(
                text="Swarm orchestration coordinates multiple AI agents to work on complex tasks. Each agent has a specific role (spec, architect, implement, test) and passes results to the next agent.",
                metadata={"topic": "swarm", "type": "architecture"}
            ),
            Document(
                text="RAG (Retrieval Augmented Generation) improves LLM responses by first retrieving relevant context from a knowledge base, then augmenting the prompt with that context.",
                metadata={"topic": "rag", "type": "technique"}
            ),
            Document(
                text="Local LLM inference using llama.cpp allows running models without cloud APIs. It supports GGUF format models and can utilize GPU acceleration via CUDA.",
                metadata={"topic": "local", "type": "inference"}
            ),
            Document(
                text="Ollama provides an easy way to run open-source LLMs locally with a simple API. It supports various models including Llama, Mistral, and Phi.",
                metadata={"topic": "ollama", "type": "tool"}
            ),
        ]
        
        self.add_documents(docs)


# Singleton
rag_knowledge = AdvancedChimeraKnowledgeBase()

if __name__ == "__main__":
    print("Advanced RAG Test")
    print("=" * 50)
    
    kb = AdvancedChimeraKnowledgeBase()
    print(f"Status: {kb.get_status()}")
    
    query = "What is quantum entanglement?"
    print(f"\nQuery: {query}")
    results = kb.retrieve(query)
    for i, doc in enumerate(results, 1):
        print(f"  {i}. {doc.text[:100]}...")
