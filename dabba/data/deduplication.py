"""
Text deduplication module. Provides exact and MinHash-based
deduplication for removing duplicate or near-duplicate documents
from training corpora.
"""

import hashlib
from typing import List, Optional, Set, Tuple
from collections import defaultdict
import random


class Deduplicator:
    """
    Document deduplication with exact matching and MinHash-based
    near-duplicate detection.

    Exact deduplication uses SHA-256 hashes of normalized text.
    MinHash deduplication uses k-shingling and MinHash signatures
    with LSH (Locality-Sensitive Hashing) for efficient approximate
    duplicate detection.

    Usage:
        dedup = Deduplicator(method="minhash", threshold=0.8)
        unique_docs = dedup.deduplicate(documents)
    """

    def __init__(
        self,
        method: str = "exact",
        num_perm: int = 128,
        threshold: float = 0.8,
        seed: int = 42,
        shingle_size: int = 5,
    ):
        """
        Initialize the deduplicator.

        Args:
            method: "exact" for exact dedup, "minhash" for near-duplicate.
            num_perm: Number of MinHash permutations (higher = more accurate).
            threshold: Jaccard similarity threshold for near-duplicates.
            seed: Random seed for MinHash hash functions.
            shingle_size: Size of character shingles for MinHash.
        """
        self.method = method
        self.num_perm = num_perm
        self.threshold = threshold
        self.seed = seed
        self.shingle_size = shingle_size

        self._seen_hashes: Set[str] = set()
        self._minhash_signatures = []

    def deduplicate(self, documents: List[str]) -> List[str]:
        """
        Deduplicate a list of documents.

        Args:
            documents: List of text documents.

        Returns:
            Deduplicated list of documents (order preserved).
        """
        if self.method == "exact":
            return self._deduplicate_exact(documents)
        elif self.method == "minhash":
            return self._deduplicate_minhash(documents)
        else:
            raise ValueError(f"Unknown dedup method: {self.method}")

    def _normalize(self, text: str) -> str:
        """
        Normalize text for deduplication by lowercasing and collapsing
        whitespace.

        Args:
            text: Input text.

        Returns:
            Normalized text.
        """
        import re
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def _exact_hash(self, text: str) -> str:
        """
        Compute SHA-256 hash of normalized text.

        Args:
            text: Input text.

        Returns:
            Hex digest string.
        """
        normalized = self._normalize(text)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _deduplicate_exact(self, documents: List[str]) -> List[str]:
        """
        Remove exact duplicates using SHA-256 hashing.

        Args:
            documents: List of text documents.

        Returns:
            Deduplicated list.
        """
        seen = set()
        unique = []
        for doc in documents:
            doc_hash = self._exact_hash(doc)
            if doc_hash not in seen:
                seen.add(doc_hash)
                unique.append(doc)
        return unique

    def _shingle(self, text: str) -> Set[int]:
        """
        Convert text to a set of hashed k-shingles.

        Args:
            text: Input text.

        Returns:
            Set of hashed shingle values.
        """
        normalized = self._normalize(text)
        shingles = set()
        for i in range(len(normalized) - self.shingle_size + 1):
            shingle = normalized[i:i + self.shingle_size]
            shingle_hash = hashlib.md5(shingle.encode("utf-8")).hexdigest()
            shingles.add(int(shingle_hash[:8], 16))
        return shingles

    def _generate_hash_functions(self) -> List[Tuple[int, int]]:
        """
        Generate random hash functions for MinHash.

        Each hash function is defined by (a, b) for h(x) = (a*x + b) % mod,
        where mod is a large prime.

        Returns:
            List of (a, b) tuples, one per permutation.
        """
        rng = random.Random(self.seed)
        mod = (1 << 61) - 1  # Large Mersenne prime
        return [(rng.randint(1, mod - 1), rng.randint(0, mod - 1))
                for _ in range(self.num_perm)]

    def _compute_signature(self, shingles: Set[int],
                           hash_funcs: List[Tuple[int, int]]) -> List[int]:
        """
        Compute MinHash signature for a set of shingles.

        Args:
            shingles: Set of hashed shingle values.
            hash_funcs: List of (a, b) hash function parameters.

        Returns:
            List of minimum hash values (one per permutation).
        """
        mod = (1 << 61) - 1
        signature = []
        for a, b in hash_funcs:
            min_hash = mod
            for shingle in shingles:
                h = (a * shingle + b) % mod
                if h < min_hash:
                    min_hash = h
            signature.append(min_hash)
        return signature

    def _jaccard_similarity(self, sig1: List[int], sig2: List[int]) -> float:
        """
        Estimate Jaccard similarity between two documents from their
        MinHash signatures.

        Args:
            sig1: MinHash signature of first document.
            sig2: MinHash signature of second document.

        Returns:
            Estimated Jaccard similarity (0.0 to 1.0).
        """
        if len(sig1) != len(sig2):
            return 0.0
        matches = sum(1 for a, b in zip(sig1, sig2) if a == b)
        return matches / len(sig1)

    def _deduplicate_minhash(self, documents: List[str]) -> List[str]:
        """
        Remove near-duplicates using MinHash with LSH.

        Documents with estimated Jaccard similarity above the threshold
        are considered duplicates; only the first occurrence is kept.

        Args:
            documents: List of text documents.

        Returns:
            Deduplicated list.
        """
        if not documents:
            return []

        hash_funcs = self._generate_hash_functions()

        signatures = []
        valid_indices = []
        for i, doc in enumerate(documents):
            shingles = self._shingle(doc)
            if shingles:
                sig = self._compute_signature(shingles, hash_funcs)
                signatures.append(sig)
                valid_indices.append(i)

        keep = [True] * len(signatures)
        for i in range(len(signatures)):
            if not keep[i]:
                continue
            for j in range(i + 1, len(signatures)):
                if not keep[j]:
                    continue
                similarity = self._jaccard_similarity(signatures[i], signatures[j])
                if similarity >= self.threshold:
                    keep[j] = False

        unique_docs = []
        for i, doc_idx in enumerate(valid_indices):
            if keep[i]:
                unique_docs.append(documents[doc_idx])

        return unique_docs

    def is_duplicate(self, text: str) -> bool:
        """
        Check if a text is a duplicate of previously seen texts
        (exact mode only).

        Args:
            text: Text to check.

        Returns:
            True if text is a duplicate.
        """
        text_hash = self._exact_hash(text)
        if text_hash in self._seen_hashes:
            return True
        self._seen_hashes.add(text_hash)
        return False
