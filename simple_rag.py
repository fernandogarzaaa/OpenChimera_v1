"""
ADVANCED SIMPLE RAG - Quantum-Inspired Local Knowledge Base
==========================================================
Upgraded with:
- Persistent disk storage (JSON-based)
- Local file indexing (add_file)
- Context-aware retrieval
- maintaining SimpleRAG and ChimeraKnowledgeBase interface
"""
import os
import json
import re
import hashlib
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

@dataclass
class Document:
    """Enhanced document representation"""
    text: str
    metadata: dict = None
    id: str = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.id is None:
            # Generate unique ID based on content
            self.id = hashlib.sha256(self.text.encode()).hexdigest()[:16]

    def to_dict(self):
        return {
            "text": self.text,
            "metadata": self.metadata,
            "id": self.id
        }


class SimpleRAG:
    """
    Enhanced Simple RAG implementation
    - In-memory vector store with persistence
    - File indexing support
    - Advanced keyword-based retrieval
    """
    
    def __init__(self, storage_path: str = "rag_storage.json"):
        self.documents: List[Document] = []
        self.index: Dict[str, List[int]] = {}  # word -> doc indices
        self.storage_path = storage_path
        self._load_from_disk()
        
    def _load_from_disk(self):
        """Load documents from disk if storage exists"""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    for doc_data in data:
                        doc = Document(
                            text=doc_data["text"],
                            metadata=doc_data.get("metadata", {}),
                            id=doc_data.get("id")
                        )
                        self._add_to_memory(doc)
                print(f"✅ Loaded {len(self.documents)} documents from {self.storage_path}")
            except Exception as e:
                print(f"⚠️ Error loading RAG storage: {e}")

    def _save_to_disk(self):
        """Save current document state to disk"""
        try:
            with open(self.storage_path, 'w') as f:
                json.dump([d.to_dict() for d in self.documents], f, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving RAG storage: {e}")

    def _add_to_memory(self, doc: Document):
        """Internal helper to add doc to in-memory index"""
        # Check for duplicates
        if any(d.id == doc.id for d in self.documents):
            return
            
        self.documents.append(doc)
        # Build simple index
        words = self._tokenize(doc.text)
        for word in words:
            if word not in self.index:
                self.index[word] = []
            self.index[word].append(len(self.documents) - 1)

    def add_documents(self, documents: List[Document]):
        """Add documents and persist to disk"""
        for doc in documents:
            self._add_to_memory(doc)
        self._save_to_disk()

    def add_file(self, path: str, metadata: Optional[dict] = None):
        """
        Index a local file into the RAG system
        Supports .txt, .md, .py, .json
        """
        if not os.path.exists(path):
            print(f"⚠️ File not found: {path}")
            return False
            
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            # Split large files into chunks
            chunks = self._chunk_text(content, chunk_size=1000)
            
            docs = []
            for i, chunk in enumerate(chunks):
                doc_metadata = {
                    "source": path,
                    "filename": os.path.basename(path),
                    "chunk": i,
                    **(metadata or {})
                }
                docs.append(Document(text=chunk, metadata=doc_metadata))
            
            self.add_documents(docs)
            print(f"✅ Indexed file: {path} ({len(docs)} chunks)")
            return True
        except Exception as e:
            print(f"⚠️ Error indexing file {path}: {e}")
            return False

    def _chunk_text(self, text: str, chunk_size: int = 1000) -> List[str]:
        """Split text into manageable chunks"""
        # Simple splitting by sentences or blocks
        chunks = []
        words = text.split()
        for i in range(0, len(words), chunk_size):
            chunks.append(" ".join(words[i:i + chunk_size]))
        return chunks

    def _tokenize(self, text: str) -> List[str]:
        """Enhanced tokenization"""
        text = text.lower()
        # Keep some characters that might be relevant for code/architecture
        text = re.sub(r'[^a-z0-9_\-\s]', ' ', text)
        return text.split()
    
    def _score(self, query: str, doc_idx: int) -> float:
        """Enhanced score document relevance to query"""
        query_tokens = self._tokenize(query)
        doc = self.documents[doc_idx]
        doc_tokens = self._tokenize(doc.text)
        
        if not query_tokens or not doc_tokens:
            return 0.0
            
        # Basic keyword overlap
        query_set = set(query_tokens)
        doc_set = set(doc_tokens)
        overlap = query_set & doc_set
        
        # Calculate base score (Jaccard-ish)
        score = len(overlap) / len(query_set)
        
        # Weight tokens (longer tokens usually more specific)
        for token in overlap:
            if len(token) > 5:
                score += 0.1
        
        # Boost by metadata
        if doc.metadata:
            for key, val in doc.metadata.items():
                if str(val).lower() in query.lower():
                    score *= 1.5
                    
        return score
    
    def retrieve(
        self, 
        query: str, 
        top_k: int = 3,
        min_score: float = 0.05
    ) -> List[Document]:
        """Retrieve most relevant documents"""
        scores = []
        
        for i in range(len(self.documents)):
            score = self._score(query, i)
            if score >= min_score:
                scores.append((i, score))
        
        # Sort by score
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Return top k
        return [self.documents[i] for i, s in scores[:top_k]]
    
    def augment(
        self, 
        query: str, 
        response: str, 
        top_k: int = 2
    ) -> str:
        """Augment response with retrieved context"""
        docs = self.retrieve(query, top_k)
        
        if not docs:
            return response
            
        # Build context
        context_parts = ["Context from knowledge base:"]
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get('filename', 'internal')
            context_parts.append(f"\n[{i}] Source: {source}\n{doc.text[:200]}...")
            
        augmented = (
            f"{response}\n\n"
            + "\n".join(context_parts)
        )
        
        return augmented
    
    def query(
        self, 
        query: str, 
        llm_callable,
        top_k: int = 3
    ) -> str:
        """Full RAG query: retrieve + augment + generate"""
        docs = self.retrieve(query, top_k)
        
        if not docs:
            return llm_callable(query)
        
        context = "\n\n".join([
            f"Document {i+1} (Source: {d.metadata.get('filename', 'unknown')}):\n{d.text}" 
            for i, d in enumerate(docs)
        ])
        
        augmented_prompt = f"""Use the following context to provide an accurate answer. 
If the context doesn't contain enough info, answer as best as you can based on your knowledge.

Context:
{context}

Question: {query}

Answer:"""
        
        return llm_callable(augmented_prompt)
    
    def get_status(self) -> dict:
        """Get RAG status"""
        return {
            "documents": len(self.documents),
            "unique_words": len(self.index),
            "storage_path": self.storage_path,
            "file_sources": list(set(d.metadata.get("filename") for d in self.documents if d.metadata.get("filename")))
        }


class ChimeraKnowledgeBase(SimpleRAG):
    """
    Persistent Knowledge Base for CHIMERA
    """
    def __init__(self, storage_path: str = "chimera_kb.json"):
        super().__init__(storage_path=storage_path)
        if not self.documents:
            self._load_default_knowledge()
        
    def _load_default_knowledge(self):
        """Initial seeding of knowledge base"""
        docs = [
            Document(
                text="CHIMERA ULTIMATE is a unified AI server running on port 7870. It integrates local inference via Ollama and llama.cpp, Swarm V3 orchestration, RAG, and Quantum Consensus.",
                metadata={"topic": "chimera", "type": "architecture"}
            ),
            Document(
                text="Swarm V3 is an advanced multi-agent framework featuring LangGraph-style checkpointing and crewAI-inspired task delegation. It supports Sequential, Parallel, Hierarchical, Map-Reduce, and Conditional execution modes.",
                metadata={"topic": "swarm", "type": "architecture"}
            ),
            Document(
                text="The Quantum Inference Engine in CHIMERA uses entanglement detection for context enhancement and quantum annealing for parameter optimization and consensus voting.",
                metadata={"topic": "quantum", "type": "inference"}
            ),
            Document(
                text="Codebuff is a specialized skill that leverages Swarm V3 for autonomous local development, including building features, fixing bugs, and reviewing code.",
                metadata={"topic": "codebuff", "type": "skill"}
            )
        ]
        self.add_documents(docs)


# Singleton
rag_knowledge = ChimeraKnowledgeBase()


if __name__ == "__main__":
    print("Advanced Simple RAG Demo")
    kb = ChimeraKnowledgeBase()
    print(f"Status: {kb.get_status()}")
    
    # Test file indexing
    test_file = "D:\\openclaw\\README.md"
    if os.path.exists(test_file):
        kb.add_file(test_file)
        print(f"Updated Status: {kb.get_status()}")
