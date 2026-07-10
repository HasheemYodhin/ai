#!/usr/bin/env python3
"""
Collect diverse training data for Dabba from Wikipedia, Project Gutenberg,
and other public sources.
"""

import json
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
import gzip
import io
import os
import sys
import time
import re
from pathlib import Path

OUTPUT_DIR = Path("data/train")
OUTPUT_FILE = OUTPUT_DIR / "dabba_training_data.txt"
LOG_FILE = Path("data/collection_log.json")

# ---- Sources ---- #

WIKIPEDIA_TOPICS = [
    "Artificial intelligence", "Machine learning", "Deep learning", "Neural network",
    "Transformer (deep learning architecture)", "Large language model", "Natural language processing",
    "Computer vision", "Reinforcement learning", "Supervised learning", "Unsupervised learning",
    "Transfer learning", "Attention (machine learning)", "Backpropagation", "Gradient descent",
    "Convolutional neural network", "Recurrent neural network", "Generative adversarial network",
    "Autoencoder", "Word embedding", "Tokenization", "BPE tokenizer",
    "Statistical machine translation", "Speech recognition", "Image recognition",
    "Object detection", "Semantic segmentation", "Named entity recognition",
    "Sentiment analysis", "Text summarization", "Question answering",
    "Knowledge graph", "Vector database", "Information retrieval",
    "Data science", "Big data", "Data mining", "Cluster analysis",
    "Dimensionality reduction", "Feature engineering", "Overfitting", "Regularization",
    "Cross-validation", "Hyperparameter optimization", "Ensemble learning",
    "Decision tree", "Random forest", "Support vector machine", "K-nearest neighbors",
    "Bayesian inference", "Markov chain", "Monte Carlo method",
    "Linear regression", "Logistic regression", "Principal component analysis",
    "t-SNE", "DBSCAN", "K-means clustering", "Collaborative filtering",
    "Recommender system", "A/B testing", "Time series analysis",
    "Python programming language", "PyTorch", "TensorFlow", "JAX",
    "CUDA", "GPU computing", "Distributed computing", "Parallel computing",
    "API", "REST API", "GraphQL", "FastAPI", "Flask (web framework)",
    "Docker (software)", "Kubernetes", "Cloud computing", "Edge computing",
    "Linux", "Unix philosophy", "Git (software)", "GitHub",
    "Functional programming", "Object-oriented programming", "Type system",
    "Compiler", "Interpreter (computing)", "Virtual machine",
    "Database", "SQL", "NoSQL", "Vector database",
    "Cryptography", "Cybersecurity", "Authentication", "Authorization",
    "Ethics of artificial intelligence", "AI safety", "Explainable AI",
    "Federated learning", "Differential privacy", "Responsible AI",
    "Robotics", "Autonomous vehicle", "Natural language generation",
    "Speech synthesis", "Text-to-speech", "Chatbot", "Conversational AI",
    "Ontology (information science)", "Semantic Web", "RDF", "SPARQL",
    "Bayesian network", "Hidden Markov model", "Conditional random field",
    "Gaussian process", "Genetic algorithm", "Swarm intelligence",
    "Quantum computing", "Neuromorphic computing", "Cognitive architecture",
    "Human-computer interaction", "Information visualization",
    "Software testing", "Debugging", "Code review", "Continuous integration",
    "Agile software development", "DevOps", "Microservices",
    "Operating system", "Memory management", "Process (computing)",
    "Thread (computing)", "Scheduling (computing)", "File system",
    "Network protocol", "TCP/IP", "HTTP", "WebSocket", "gRPC",
    "Data structure", "Algorithm", "Computational complexity theory",
    "Sorting algorithm", "Search algorithm", "Graph theory",
    "Hash table", "Binary tree", "Heap (data structure)", "Linked list",
    "Stack (abstract data type)", "Queue (abstract data type)",
    "Dynamic programming", "Greedy algorithm", "Divide and conquer algorithm",
    "Recursion", "Big O notation", "NP-completeness",
    "Software architecture", "Design pattern", "Model-view-controller",
    "Functional programming language", "Haskell", "Rust (programming language)",
    "C (programming language)", "C++", "JavaScript", "TypeScript",
    "Go (programming language)", "Java (programming language)",
    "Mathematics", "Calculus", "Linear algebra", "Probability theory",
    "Statistics", "Information theory", "Optimization (mathematics)",
    "Differential equation", "Fourier transform", "Signal processing",
    "Thermodynamics", "Quantum mechanics", "Electromagnetism",
    "Biology", "Neuroscience", "Cognitive science", "Linguistics",
    "Philosophy of mind", "Consciousness", "Intelligence",
    "Alan Turing", "Turing test", "Chinese room", "Symbolic AI",
    "Expert system", "Knowledge representation", "Logic programming",
    "Prolog", "Lisp (programming language)", "History of artificial intelligence",
    "AI winter", "Deep Blue", "AlphaGo", "GPT-3", "GPT-4", "Claude (language model)",
    "Llama (language model)", "BERT (language model)", "T5 (language model)",
    "Retrieval-augmented generation", "Prompt engineering", "Chain-of-thought prompting",
    "Few-shot learning", "Zero-shot learning", "Fine-tuning (deep learning)",
    "RLHF", "Instruction tuning", "Constitutional AI", "Model compression",
    "Knowledge distillation", "Quantization (signal processing)", "Pruning (artificial neural network)",
    "Mixture of experts", "Sparse model", "Attention is All You Need",
]

GUTENBERG_BOOKS = [
    # Classic AI/philosophy relevant works
    ("https://www.gutenberg.org/cache/epub/5827/pg5827.txt", "The Art of War"),
    ("https://www.gutenberg.org/cache/epub/1342/pg1342.txt", "Pride and Prejudice"),
    ("https://www.gutenberg.org/cache/epub/84/pg84.txt", "Frankenstein"),
    ("https://www.gutenberg.org/cache/epub/11/pg11.txt", "Alice in Wonderland"),
    ("https://www.gutenberg.org/cache/epub/1661/pg1661.txt", "The Adventures of Sherlock Holmes"),
    ("https://www.gutenberg.org/cache/epub/2701/pg2701.txt", "Moby Dick"),
    ("https://www.gutenberg.org/cache/epub/1260/pg1260.txt", "Jane Eyre"),
    ("https://www.gutenberg.org/cache/epub/43/pg43.txt", "Dracula"),
    ("https://www.gutenberg.org/cache/epub/345/pg345.txt", "The Time Machine"),
    ("https://www.gutenberg.org/cache/epub/36/pg36.txt", "The War of the Worlds"),
    ("https://www.gutenberg.org/cache/epub/526/pg526.txt", "The Republic (Plato)"),
    ("https://www.gutenberg.org/cache/epub/3300/pg3300.txt", "The Analects of Confucius"),
    ("https://www.gutenberg.org/cache/epub/3207/pg3207.txt", "Leviathan (Hobbes)"),
    ("https://www.gutenberg.org/cache/epub/1232/pg1232.txt", "Meditations (Marcus Aurelius)"),
    ("https://www.gutenberg.org/cache/epub/1497/pg1497.txt", "The Republic (Cicero)"),
]

GUTENBERG_SCIENCE = [
    ("https://www.gutenberg.org/cache/epub/5001/pg5001.txt", "Relativity (Einstein)"),
    ("https://www.gutenberg.org/cache/epub/41069/pg41069.txt", "The Foundations of Science"),
    ("https://www.gutenberg.org/cache/epub/37729/pg37729.txt", "The Analysis of Mind (Russell)"),
    ("https://www.gutenberg.org/cache/epub/25215/pg25215.txt", "Principles of Mathematics (Russell)"),
    ("https://www.gutenberg.org/cache/epub/30104/pg30104.txt", "The Problems of Philosophy (Russell)"),
    ("https://www.gutenberg.org/cache/epub/5822/pg5822.txt", "The Descent of Man (Darwin)"),
    ("https://www.gutenberg.org/cache/epub/1228/pg1228.txt", "The Origin of Species (Darwin)"),
    ("https://www.gutenberg.org/cache/epub/29488/pg29488.txt", "The Mind and the Brain"),
    ("https://www.gutenberg.org/cache/epub/35496/pg35496.txt", "Intelligence (Binet)"),
]

CODE_CATEGORIES = {
    "Python": """Python is a high-level, interpreted programming language known for its readability and versatility. It supports multiple programming paradigms including procedural, object-oriented, and functional programming. Python's design philosophy emphasizes code readability with significant indentation. The language has a comprehensive standard library and a vast ecosystem of third-party packages. Key features include dynamic typing, automatic memory management, and a rich set of data structures like lists, dictionaries, sets, and tuples. Python is widely used in data science, machine learning, web development, automation, and scientific computing. Popular frameworks include Django for web development, Flask for microservices, and PyTorch for deep learning. Python's package manager pip enables easy installation of libraries from the Python Package Index (PyPI).""",

    "JavaScript": """JavaScript is a high-level, dynamic programming language that conforms to the ECMAScript specification. It is a core technology of the World Wide Web, enabling interactive web pages and is an essential part of web applications. JavaScript supports event-driven, functional, and imperative programming styles. It has dynamic typing, prototype-based object-orientation, and first-class functions. Node.js allows JavaScript to run on servers. Modern JavaScript includes features like Promises for asynchronous operations, async/await syntax, modules, arrow functions, template literals, destructuring, and the spread operator. Popular frameworks include React, Vue, Angular for frontend and Express for backend development. TypeScript adds optional static typing to JavaScript.""",

    "C": """C is a general-purpose, procedural computer programming language developed by Dennis Ritchie at Bell Labs. It provides low-level memory access with a simple set of keywords. C is widely used in system programming, embedded systems, and operating systems. The language has influenced many other languages including C++, C#, Java, and Python. C programs are compiled to machine code, making them efficient and fast. Key concepts include pointers, manual memory management using malloc and free, structured programming with functions, and the preprocessor for macros. The C standard library provides functions for input/output, string manipulation, mathematical operations, and memory allocation.""",

    "Data Structures": """Data structures organize and store data for efficient access and modification. Arrays store elements in contiguous memory with constant-time indexing. Linked lists consist of nodes connected by pointers, enabling efficient insertions and deletions. Stacks follow Last-In-First-Out (LIFO) order, useful for function calls and undo operations. Queues follow First-In-First-Out (FIFO) order, used in scheduling and breadth-first search. Hash tables provide average constant-time lookup by mapping keys to positions using a hash function. Trees organize data hierarchically, with binary search trees enabling efficient searching. Heaps maintain partial ordering for priority queues. Graphs represent networks of connected nodes. Choosing the right data structure is crucial for algorithm efficiency.""",

    "Algorithms": """Algorithms are step-by-step procedures for solving computational problems. Sorting algorithms like Quicksort, Mergesort, and Heapsort arrange data in order. Search algorithms find elements in data structures, with binary search achieving logarithmic time on sorted arrays. Graph algorithms include Dijkstra's shortest path, Depth-First Search (DFS), and Breadth-First Search (BFS). Dynamic programming solves problems by breaking them into overlapping subproblems and storing results. Greedy algorithms make locally optimal choices at each step. Divide-and-conquer algorithms split problems into smaller instances. String algorithms search for patterns in text. Algorithm analysis uses Big O notation to describe time and space complexity. Understanding algorithms is fundamental to writing efficient software.""",

    "REST API Design": """REST (Representational State Transfer) is an architectural style for designing networked applications. REST APIs use HTTP methods: GET for retrieval, POST for creation, PUT for updates, DELETE for removal, and PATCH for partial modifications. Resources are identified by URLs and represented in formats like JSON or XML. REST APIs should be stateless, meaning each request contains all necessary information. Good practices include using proper HTTP status codes, versioning APIs through URLs or headers, implementing pagination for list endpoints, providing consistent error responses, authenticating requests with tokens, rate limiting to prevent abuse, and documenting endpoints using OpenAPI/Swagger. HATEOAS includes links in responses to guide clients through the API.""",

    "Operating Systems": """An operating system manages computer hardware and provides services to applications. The kernel is the core component that handles process scheduling, memory management, device drivers, and system calls. Processes are isolated units of execution with their own address space. Threads allow parallel execution within a process, sharing memory. The scheduler determines which process runs next using algorithms like round-robin, priority-based, or multi-level feedback queue. Memory management uses virtual memory, paging, and segmentation to efficiently allocate memory. File systems organize data on storage devices with directory hierarchies and permissions. Inter-process communication includes pipes, sockets, shared memory, and message passing. Synchronization primitives like mutexes, semaphores, and condition variables prevent race conditions in concurrent programs.""",

    "Networking": """Computer networking enables communication between devices. The OSI model has seven layers: Physical, Data Link, Network, Transport, Session, Presentation, and Application. The TCP/IP protocol suite is the foundation of the internet. TCP provides reliable, connection-oriented communication with flow control and congestion avoidance. UDP offers lightweight, connectionless datagram delivery. IP handles addressing and routing across networks. DNS translates domain names to IP addresses. HTTP and HTTPS enable web communication. TLS provides encryption for secure data transfer. Sockets are the API for network programming. Key concepts include IP addresses, port numbers, subnet masks, routing protocols, NAT, firewalls, load balancers, and content delivery networks.""" 
}

USER_AGENT = "DabbaTrainingBot/1.0 (educational project)"


def fetch_url(url: str, timeout: int = 15) -> str | None:
    """Fetch content from a URL with retries."""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                # Handle gzip encoding
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                try:
                    return data.decode("utf-8")
                except UnicodeDecodeError:
                    return data.decode("latin-1")
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"  ✗ Failed to fetch {url}: {e}")
                return None


def fetch_wikipedia_article(title: str) -> str | None:
    """Fetch a Wikipedia article via the REST API."""
    api_url = "https://en.wikipedia.org/w/api.php"
    params = (
        f"{api_url}?action=query&format=json&titles={urllib.parse.quote(title)}"
        "&prop=extracts&explaintext=True&exlimit=1&exintro=False"
    )
    data = fetch_url(params, timeout=10)
    if not data:
        return None
    try:
        parsed = json.loads(data)
        pages = parsed.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            extract = page_data.get("extract", "")
            if extract:
                return extract.strip()
    except Exception:
        pass
    return None


def clean_gutenberg_text(text: str) -> str:
    """Strip Gutenberg header/footer boilerplate."""
    start = text.find("*** START OF THE PROJECT GUTENBERG")
    if start == -1:
        start = text.find("*** START OF THIS PROJECT GUTENBERG")
    if start == -1:
        start = 0
    end = text.find("*** END OF THE PROJECT GUTENBERG")
    if end == -1:
        end = text.find("*** END OF THIS PROJECT GUTENBERG")
    if end == -1:
        end = len(text)
    content = text[start:end] if start > 0 else text[:end]
    # Remove excessive blank lines
    content = re.sub(r'\n{4,}', '\n\n\n', content)
    return content.strip()


def format_qa_pairs(text: str, max_words: int = 250) -> list[str]:
    """Break a long text into Q&A-style entries for training."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    lines = []
    current_chunk = []
    current_words = 0
    for sent in sentences:
        wc = len(sent.split())
        if current_words + wc > max_words and current_chunk:
            combined = " ".join(current_chunk).strip()
            if combined:
                lines.append(combined)
            current_chunk = [sent]
            current_words = wc
        else:
            current_chunk.append(sent)
            current_words += wc
    if current_chunk:
        combined = " ".join(current_chunk).strip()
        if combined:
            lines.append(combined)
    return lines


def make_qa_line(text: str, topic: str = "") -> str:
    """Wrap text as a Q&A line if it doesn't end with sentence-ending punctuation."""
    text = text.strip()
    if not text:
        return ""
    if topic and not text.lower().startswith(("what", "how", "why", "explain", "describe", "define")):
        return f"What is {topic}? {text}"
    return text


def collect_wikipedia(max_articles: int = 200) -> list[str]:
    """Collect Wikipedia articles on AI/ML topics."""
    print(f"\n{'='*60}")
    print(f"📖 Fetching Wikipedia articles (up to {max_articles})")
    print(f"{'='*60}")
    lines = []
    count = 0
    for i, topic in enumerate(WIKIPEDIA_TOPICS):
        if count >= max_articles:
            break
        print(f"  [{i+1}/{len(WIKIPEDIA_TOPICS)}] {topic[:50]}... ", end="", flush=True)
        content = fetch_wikipedia_article(topic)
        if content and len(content) > 100:
            article_lines = format_qa_pairs(content)
            for al in article_lines:
                line = make_qa_line(al, topic)
                if line:
                    lines.append(line)
            count += 1
            print(f"✓ ({len(content):,} chars, {len(article_lines)} lines)")
        else:
            print("✗ empty")
        time.sleep(0.5)
    print(f"\n  Total: {count} articles, {len(lines):,} lines")
    return lines


def collect_gutenberg(books: list[tuple[str, str]], label: str) -> list[str]:
    """Download and process Project Gutenberg books."""
    print(f"\n{'='*60}")
    print(f"📚 Fetching {label} ({len(books)} books)")
    print(f"{'='*60}")
    lines = []
    for url, title in books:
        print(f"  📖 {title}... ", end="", flush=True)
        text = fetch_url(url, timeout=30)
        if text and len(text) > 5000:
            clean = clean_gutenberg_text(text)
            # Split into chunks of ~200 words each
            chunks = format_qa_pairs(clean, max_words=200)
            lines.extend(chunks)
            print(f"✓ ({len(clean):,} chars, {len(chunks)} lines)")
        else:
            print(f"✗ empty or too short")
        time.sleep(1)
    print(f"  Total: {len(lines):,} lines")
    return lines


def collect_code_knowledge() -> list[str]:
    """Add structured code/tool knowledge entries."""
    print(f"\n{'='*60}")
    print(f"💻 Adding code knowledge entries")
    print(f"{'='*60}")
    lines = []
    for category, text in CODE_CATEGORIES.items():
        print(f"  📝 {category}")
        lines.append(text)
    print(f"  Total: {len(lines)} entries")
    return lines


def deduplicate_and_merge(existing: list[str], new_lines: list[str]) -> list[str]:
    """Deduplicate lines and merge with existing data."""
    seen = set()
    merged = []
    for line in existing + new_lines:
        line = line.strip()
        if not line:
            continue
        # Use first 60 chars as dedup key
        key = line[:60]
        if key not in seen:
            seen.add(key)
            merged.append(line)
    print(f"  Dedup: {len(existing)+len(new_lines)} → {len(merged)} unique lines")
    return merged


def report_stats(lines: list[str], output_path: Path):
    """Print statistics about the collected dataset."""
    total_chars = sum(len(l) for l in lines)
    total_words = sum(len(l.split()) for l in lines)
    avg_line_len = total_chars / len(lines) if lines else 0
    print(f"\n{'='*60}")
    print(f"📊 DATASET STATISTICS")
    print(f"{'='*60}")
    print(f"  Lines:         {len(lines):,}")
    print(f"  Characters:    {total_chars:,}")
    print(f"  Words:         {total_words:,}")
    print(f"  Avg line len:  {avg_line_len:.0f} chars")
    print(f"  Est. tokens:   ~{total_chars // 4:,} (at ~4 chars/token)")
    print(f"  Output path:   {output_path}")
    print(f"  Size on disk:  {total_chars / 1024 / 1024:.1f} MB")


def main():
    print("="*60)
    print("🤖 DABBA TRAINING DATA COLLECTOR")
    print("="*60)

    # Ensure output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing data
    existing_lines = []
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            existing_lines = [l.strip() for l in f if l.strip()]
        print(f"\n📂 Existing data: {len(existing_lines):,} lines")

    # Collect from all sources
    all_new_lines = []

    # 1. Wikipedia (top ~150 articles)
    wiki_lines = collect_wikipedia(max_articles=150)
    all_new_lines.extend(wiki_lines)

    # 2. Classic books (philosophy, literature)
    book_lines = collect_gutenberg(GUTENBERG_BOOKS, "classic books")
    all_new_lines.extend(book_lines)

    # 3. Science books
    science_lines = collect_gutenberg(GUTENBERG_SCIENCE, "science books")
    all_new_lines.extend(science_lines)

    # 4. Code knowledge
    code_lines = collect_code_knowledge()
    all_new_lines.extend(code_lines)

    # Merge and deduplicate
    merged = deduplicate_and_merge(existing_lines, all_new_lines)

    # Write output
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for line in merged:
            f.write(line + '\n')

    report_stats(merged, OUTPUT_FILE)

    # Save collection log
    log = {
        "total_lines": len(merged),
        "new_lines_added": len(merged) - len(existing_lines),
        "sources": {
            "wikipedia_topics_attempted": len(WIKIPEDIA_TOPICS),
            "gutenberg_books": len(GUTENBERG_BOOKS),
            "gutenberg_science": len(GUTENBERG_SCIENCE),
            "code_categories": len(CODE_CATEGORIES),
        }
    }
    with open(LOG_FILE, 'w') as f:
        json.dump(log, f, indent=2)

    print(f"\n{'='*60}")
    print("✅ DATA COLLECTION COMPLETE!")
    print(f"{'='*60}")
    print(f"\nNext step: Run 'python3 train_dabba.py' to retrain the model.")


if __name__ == "__main__":
    main()
