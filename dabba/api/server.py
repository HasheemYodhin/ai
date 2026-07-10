"""
Main FastAPI application for the dabba inference server.

Creates and configures the FastAPI app with all routes, middleware,
authentication, rate limiting, CORS, and health checks.
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dabba.config.api_config import ApiConfig
from dabba.api.auth import ApiKeyAuth
from dabba.api.rate_limiter import RateLimiter
from dabba.api.chat_endpoints import create_chat_router
from dabba.api.embedding_endpoints import create_embedding_router
from dabba.api.model_endpoints import create_model_router


class ModelEngine:
    """
    Wrapper for the underlying model inference engine.

    Provides a unified interface for the API server to interact with
    different model backends (dabba native, vLLM, Ollama, etc.).

    Args:
        model_path: Path to the model or model name.
        device: Device to run on ("cpu", "cuda").
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cpu",
    ):
        self.model_path = model_path or os.environ.get("DABBA_MODEL_PATH") or "./checkpoints/dabba-model/final"
        self.device = device
        self.model = None
        self.tokenizer = None
        self.config = None
        self._gguf = None

    def load(self) -> None:
        """Load your trained Dabba model — GGUF (Colab-trained) or native checkpoint."""
        if self.model_path == "rule_based":
            logging.info("Using rule-based knowledge engine fallback.")
            self.model = "rule_based"
            self.tokenizer = None
            return
        if str(self.model_path).endswith(".gguf"):
            self._load_gguf()
            return
        try:
            import torch
            from pathlib import Path
            from dabba.model.transformer import Transformer
            from dabba.tokenizer.bpe_tokenizer import BPETokenizer
            from dabba.inference.generator import Generator

            model_path = Path(self.model_path)
            logging.info(f"Loading Dabba from {model_path}...")

            if not (model_path / "model.pt").exists():
                raise FileNotFoundError(f"Model not found at {model_path}")

            # Load config and model
            config_data = torch.load(model_path / "config.pt", map_location=self.device, weights_only=False)
            config = config_data["config"]

            model = Transformer(config).to(self.device)
            model.load_state_dict(torch.load(model_path / "model.pt", map_location=self.device, weights_only=False))
            model.eval()

            # Load the saved tokenizer (must match vocab_size used during training)
            tokenizer_path = Path("./checkpoints/tokenizer/bpe_tokenizer.json")
            if not tokenizer_path.exists():
                raise FileNotFoundError(f"Tokenizer not found at {tokenizer_path}")
            tokenizer = BPETokenizer.load(str(tokenizer_path))

            # Verify vocab size matches the model
            actual_vocab = len(tokenizer.vocab)
            if actual_vocab != config.vocab_size:
                logging.warning(
                    f"Vocab size mismatch: tokenizer={actual_vocab}, model={config.vocab_size}. "
                    "Run train_dabba.py to retrain with consistent sizes."
                )

            self.model = Generator(model, tokenizer=tokenizer, eos_token_id=2, pad_token_id=0)
            self.tokenizer = tokenizer
            self.config = config

            logging.info("✨ DABBA model loaded successfully!")
            logging.info(f"   Model: {config.num_params / 1e6:.1f}M parameters")
            logging.info(f"   Layers: {config.num_layers}")
        except Exception as e:
            logging.warning(f"Dabba loading failed: {e}. Falling back to knowledge base.")
            self.model = "rule_based"
            self.tokenizer = None

    def _load_gguf(self) -> None:
        """Load a .gguf model (e.g. your Colab fine-tuned Dabba 8B) via llama.cpp."""
        try:
            from dabba.inference.gguf_engine import GGUFEngine

            logging.info(f"Loading GGUF model from {self.model_path}...")
            self._gguf = GGUFEngine(
                model_path=self.model_path,
                n_ctx=int(os.environ.get("DABBA_N_CTX", "4096")),
                n_gpu_layers=int(os.environ.get("DABBA_N_GPU_LAYERS", "0")),
            )
            self._gguf.load()
            self.model = "gguf"
            logging.info("✨ Dabba GGUF model loaded successfully — running natively, no Ollama!")
        except ImportError:
            logging.warning(
                "llama-cpp-python not installed. Run: pip install llama-cpp-python"
            )
            self.model = "rule_based"
        except Exception as e:
            logging.warning(f"GGUF loading failed: {e}. Falling back to knowledge base.")
            self.model = "rule_based"

    def _is_garbage(self, text: str) -> bool:
        """Detect low-quality model output (repetition, too short, etc.)."""
        if not text or len(text) < 10:
            return True
        char_counts = {}
        for ch in text:
            char_counts[ch] = char_counts.get(ch, 0) + 1
        most_common_ratio = max(char_counts.values()) / len(text)
        if most_common_ratio > 0.4:
            return True
        words = text.split()
        if len(words) >= 4:
            unique_bigrams = set()
            for i in range(len(words) - 1):
                unique_bigrams.add((words[i], words[i + 1]))
            total_bigrams = len(words) - 1
            if total_bigrams > 0:
                bigram_repetition_ratio = 1.0 - (len(unique_bigrams) / total_bigrams)
                if bigram_repetition_ratio > 0.6:
                    return True
        return False

    def chat(self, messages: list, temperature: float = 0.7, max_tokens: Optional[int] = None, **kwargs) -> str:
        """
        Full-conversation chat.

        Priority: real GGUF model (if loaded) > trained native checkpoint > rule-based
        tool-detection fallback. NOTE: there used to be a second `chat()` defined later
        in this class that silently shadowed this one (Python keeps the last definition
        of a method) — that bug is why GGUF/native routing never actually ran. Fixed by
        merging both into this single method.
        """
        if self.model == "gguf" and self._gguf is not None:
            try:
                return self._gguf.chat(messages, max_tokens=max_tokens or 512, temperature=temperature)
            except Exception as e:
                logging.error(f"GGUF chat failed: {e}. Falling back.")

        if not messages:
            return "How can I help you?"

        last_user = ""
        tool_results: List[str] = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "") or ""
            if role == "user":
                last_user = content
            elif role == "tool":
                tool_results.append(content)

        # Native trained checkpoint gets a real shot before the regex fallback
        if self.model not in ("rule_based", "gguf", None) and not isinstance(self.model, str):
            try:
                generated = self.generate(last_user, max_tokens=max_tokens or 200, temperature=temperature)
                if generated and not self._is_garbage(generated):
                    return generated
            except Exception as e:
                logging.error(f"Native chat generation failed: {e}. Falling back to rule-based.")

        if tool_results:
            return self._summarize_tool_results(last_user, tool_results)

        tool_response = self._detect_tool_call(last_user)
        if tool_response:
            return tool_response

        return self._generate_rule_based(last_user)

    def generate(self, prompt: str, max_tokens: int = 100, **kwargs) -> str:
        """Generate text using trained Dabba model."""
        if self.model == "gguf" and self._gguf is not None:
            try:
                return self._gguf.generate(prompt, max_tokens=max_tokens, **kwargs)
            except Exception as e:
                logging.error(f"GGUF generation failed: {e}. Using knowledge base.")
                return self._generate_rule_based(prompt)

        if self.model == "rule_based" or not self.model or isinstance(self.model, str):
            return self._generate_rule_based(prompt)

        try:
            # Use the trained Dabba model for generation
            import torch

            # Tokenize the prompt. nn.Module has no built-in `.device` attribute —
            # read it off an actual parameter tensor instead (this used to crash
            # every native-model generation with "'Transformer' object has no
            # attribute 'device'", silently falling back to the rule-based engine).
            input_ids = self.tokenizer.encode(prompt)
            model_device = next(self.model.model.parameters()).device
            input_tensor = torch.tensor([input_ids], dtype=torch.long, device=model_device)

            response = self.model.generate(
                input_tensor,
                max_tokens=max_tokens,
                temperature=kwargs.get("temperature", 0.8),
                top_k=kwargs.get("top_k", 40),
                top_p=kwargs.get("top_p", 0.95),
                do_sample=True,
            )

            # Decode the generated tokens
            generated_tokens = response[0].tolist()
            generated_text = self.tokenizer.decode(generated_tokens)

            # If we got substantial and non-garbage output, use it
            if generated_text and len(generated_text) > 10 and not self._is_garbage(generated_text):
                return generated_text.strip()
            else:
                return self._generate_rule_based(prompt)

        except Exception as e:
            logging.error(f"Dabba generation failed: {e}. Using knowledge base.")
            return self._generate_rule_based(prompt)

    # Comprehensive knowledge base shared across all instances
    _KNOWLEDGE: dict = {
        # ---- AI / ML ----
        "llm": "Large language models (LLMs) are transformer-based neural networks trained on trillions of tokens to predict the next token. With billions of parameters they develop language understanding, reasoning, and world knowledge. Examples: GPT-4, Claude, Llama, Gemini. They can generate text, translate, summarize, write code, and answer questions. Fine-tuning and prompt engineering adapt them to specific tasks.",
        "gpt": "GPT (Generative Pre-trained Transformer) is a series of large language models by OpenAI. They use a decoder-only transformer trained on next-token prediction. GPT-3 (175B params) showed emergent in-context learning; GPT-4 added multimodality and improved reasoning. GPTs are fine-tuned with RLHF for helpfulness and safety.",
        "claude": "Claude is an AI assistant by Anthropic, designed to be helpful, harmless, and honest using Constitutional AI. It excels at careful reasoning, long-context tasks (up to 200K tokens), and nuanced conversation. Claude is trained to admit uncertainty and refuse harmful requests.",
        "rag": "Retrieval-Augmented Generation (RAG) combines a retriever and a language model. The retriever searches a vector database for documents relevant to the query; the LLM then generates a response grounded in those documents. Benefits: reduces hallucinations, enables private/recent data, and allows citing sources. Core components: embedding model, vector store, LLM.",
        "retrieval-augmented generation": "Retrieval-Augmented Generation (RAG) combines a retriever and a language model. The retriever searches a vector database for documents relevant to the query; the LLM then generates a response grounded in those documents. Benefits: reduces hallucinations, enables private/recent data, and allows citing sources.",
        "fine-tuning": "Fine-tuning continues training a pre-trained model on a smaller, task-specific dataset. A lower learning rate preserves pre-trained knowledge while specializing behavior. Methods: full fine-tuning, LoRA (low-rank adapters), QLoRA, and prompt tuning. Used for instruction following, domain adaptation, and safety alignment.",
        "machine learning": "Machine learning enables computers to learn patterns from data without explicit programming. A model trains on examples, discovers statistical patterns, and predicts on new data. Three main paradigms: supervised learning (labeled examples), unsupervised learning (hidden structure), and reinforcement learning (rewards). Common algorithms: neural networks, decision trees, SVMs, k-means.",
        "deep learning": "Deep learning uses neural networks with many layers. Early layers detect simple features; deeper layers build complex abstractions. Key architectures: CNNs (images), RNNs (sequences), Transformers (language). Powers image recognition, speech assistants, and LLMs. Training requires GPUs and large datasets.",
        "neural network": "Neural networks are computational models inspired by the brain, made of layers of connected nodes (neurons). Each connection has a learnable weight. Backpropagation adjusts weights to minimize prediction error. Activation functions (ReLU, sigmoid) add non-linearity. With enough layers and data they approximate nearly any function.",
        "transformer": "The Transformer (2017, 'Attention Is All You Need') replaced recurrence with self-attention, letting every token attend to every other token in parallel. This captures long-range dependencies efficiently. Encoder-only (BERT), decoder-only (GPT), and encoder-decoder (T5) variants serve different tasks. Foundation of all modern LLMs.",
        "attention mechanism": "Attention computes, for each token, a weighted sum of other tokens' values based on query-key similarity. Scaled dot-product attention: softmax(QK^T / sqrt(d_k)) V. Multi-head attention runs this in parallel with different projections, capturing diverse relationships. Enables transformers to focus on relevant context anywhere in the sequence.",
        "natural language processing": "NLP is the AI field focused on understanding and generating human language. Tasks: sentiment analysis, machine translation, question answering, named entity recognition, summarization, and parsing. Modern NLP is dominated by transformer-based LLMs (BERT, GPT, T5) pretrained on massive corpora.",
        "nlp": "NLP (Natural Language Processing) enables computers to understand and generate human language. Key tasks: sentiment analysis, translation, QA, NER, summarization. Powered by transformer-based LLMs pretrained on massive text corpora.",
        "reinforcement learning": "Reinforcement learning trains an agent to maximize cumulative reward by interacting with an environment. Key algorithms: Q-learning, DQN, PPO, A3C. Achieved superhuman performance in chess, Go, and video games. Used in robotics, recommendation systems, and RLHF for LLM alignment.",
        "embeddings": "Embeddings are dense numerical vectors representing data in a continuous semantic space. Similar items have similar vectors. Word2Vec, GloVe, and contextual embeddings from BERT/GPT are common types. Used for semantic search, recommendation, clustering, and as the input layer of neural networks.",
        "vector database": "A vector database stores embeddings and supports fast approximate nearest-neighbor search (HNSW, IVF). Enables semantic search: find items similar in meaning to a query. Core component of RAG systems. Popular options: Pinecone, Weaviate, Chroma, Qdrant, pgvector.",
        "prompt engineering": "Prompt engineering designs inputs to LLMs to improve outputs. Techniques: zero-shot (direct ask), few-shot (examples in prompt), chain-of-thought (step-by-step reasoning), structured output (format instructions). Effective prompts specify context, role, constraints, and desired format without changing model weights.",
        "tokenization": "Tokenization breaks text into tokens for language models. Subword methods (BPE, WordPiece) balance vocabulary size with coverage. ~1 token per 4 English characters. Special tokens ([CLS], [SEP], [PAD]) serve structural roles. The tokenizer must match the one used during training.",
        "backpropagation": "Backpropagation computes gradients of the loss through a neural network using the chain rule. Forward pass: compute predictions. Backward pass: propagate error gradient layer by layer, computing each weight's contribution to the error. Optimization algorithms then update weights to reduce loss.",
        "gradient descent": "Gradient descent minimizes a loss function by iteratively moving parameters in the direction of steepest descent (negative gradient). Variants: batch (full dataset), stochastic (single sample), mini-batch (small subset). Adaptive optimizers like Adam adjust per-parameter learning rates based on gradient history.",
        "supervised learning": "Supervised learning trains a model on labeled (input, output) pairs. Tasks: classification (predicting categories) and regression (predicting values). The model minimizes the error between predicted and actual labels. Algorithms: linear regression, logistic regression, neural networks, decision trees, SVMs.",
        "unsupervised learning": "Unsupervised learning finds patterns in unlabeled data. Tasks: clustering (k-means, DBSCAN), dimensionality reduction (PCA, t-SNE), density estimation, and anomaly detection. Also includes self-supervised learning—creating labels from the data itself, as in masked language modeling.",
        "transfer learning": "Transfer learning reuses knowledge from a model pretrained on large data for a new, related task. Fine-tuning adapts the pretrained model with minimal additional training. Dramatically reduces data and compute requirements. The dominant paradigm in NLP (pretrain on web text, fine-tune on task) and computer vision (pretrain on ImageNet).",
        "hallucination": "Hallucination is when an AI model confidently generates false information. Happens because models predict likely text, not verified facts. Mitigation: RAG (grounding in retrieved sources), careful prompting, and calibration training. Always verify critical claims from LLMs.",
        "artificial intelligence": "Artificial Intelligence (AI) is the field of building systems that perform tasks requiring human-like intelligence: learning, reasoning, perception, language, and decision-making. Subfields include ML, deep learning, NLP, and computer vision. Narrow AI excels at specific tasks; general AI (AGI) remains theoretical.",
        "ai": "AI (Artificial Intelligence) builds systems that can learn, reason, and solve problems. Subfields: machine learning, deep learning, NLP, computer vision, robotics. Current AI is narrow (excels at specific tasks). Breakthroughs in deep learning and transformers have dramatically accelerated progress.",
        # ---- CS / Programming ----
        "api": "An API (Application Programming Interface) defines how software components communicate. REST APIs use HTTP (GET, POST, PUT, DELETE) and JSON. Good API design: clear endpoints, versioning, authentication, rate limiting, and docs. APIs enable modular systems where services expose capabilities without revealing internals.",
        "git": "Git is a distributed version control system. Every developer has a full repository copy. Key concepts: commits (snapshots), branches, merges, pull requests. Common commands: clone, add, commit, push, pull, branch, merge, log. Platforms: GitHub, GitLab, Bitbucket.",
        "docker": "Docker packages applications into containers—isolated environments with code, runtime, and dependencies. Containers share the host OS kernel, making them faster than VMs. Images are built from Dockerfiles; Docker Compose manages multi-container apps; Kubernetes orchestrates at scale.",
        "sql": "SQL (Structured Query Language) is the standard for relational databases. SELECT queries data; INSERT/UPDATE/DELETE modifies it; CREATE/ALTER/DROP manages schema. JOINs combine tables. GROUP BY aggregates. Databases: PostgreSQL, MySQL, SQLite, SQL Server.",
        "python": "Python is a high-level, dynamically typed language known for readable syntax and large ecosystem. Used in data science, ML, web development, scripting. Key features: list comprehensions, generators, decorators, first-class functions. Frameworks: Django/Flask (web), NumPy/Pandas (data), PyTorch/TensorFlow (ML).",
        "hash table": "A hash table maps keys to values via a hash function that computes array indices. O(1) average lookup, insert, delete. Collisions handled by chaining or open addressing. Python dict, JavaScript Map, and Java HashMap are hash tables.",
        "object-oriented programming": "OOP organizes code as objects that combine data (attributes) and behavior (methods). Four pillars: encapsulation, inheritance, polymorphism, abstraction. Languages: Python, Java, C++, C#. Design patterns (Singleton, Factory, Observer) are common OOP solutions.",
        "microservices": "Microservices splits an application into small, independent services each focused on one business capability. Services communicate via APIs or message queues, deploy independently, and can use different tech stacks. Benefits: scalability, team autonomy, fault isolation. Challenges: distributed complexity and operational overhead.",
        "fastapi": "FastAPI is a modern Python web framework for building APIs. Features: async support, automatic Swagger/OpenAPI docs, Pydantic validation, dependency injection, WebSocket support. High performance, comparable to Node.js. Used for REST APIs, ML model serving, and microservices.",
        "kubernetes": "Kubernetes (K8s) is an open-source container orchestration platform. It automates deployment, scaling, and management of containerized applications across clusters. Key concepts: pods (groups of containers), services (networking), deployments (desired state), and namespaces (isolation).",
        # ---- General Science ----
        "photosynthesis": "Photosynthesis converts sunlight, CO2, and water into glucose and oxygen in plant chloroplasts. Light reactions produce ATP and NADPH by splitting water. The Calvin cycle uses that energy to fix CO2 into sugars. Photosynthesis produces Earth's atmospheric oxygen and is the base of most food chains.",
        "dna": "DNA (deoxyribonucleic acid) carries genetic information as a double helix of base pairs (A-T, G-C). Genes are DNA segments that encode proteins. DNA replicates before cell division. Mutations drive evolution or cause disease. The human genome has ~3 billion base pairs encoding ~20,000 genes.",
        "gravity": "Gravity is the attractive force between masses. On Earth: 9.8 m/s² acceleration. Newton: F = GMm/r². Einstein's general relativity: gravity is spacetime curvature caused by mass/energy. Governs planetary orbits, tides, stellar structure, and the large-scale universe.",
        "electricity": "Electricity is the flow of electric charge through a conductor. Voltage (V) is potential difference; current (A) is charge flow rate; resistance (Ω) opposes flow. Ohm's Law: V = IR. AC alternates direction (power grids); DC flows one way (batteries). Powers virtually all modern technology.",
        "evolution": "Evolution is change in heritable traits across generations. Natural selection favors traits that improve survival and reproduction. Genetic variation arises from mutations and sexual reproduction. Darwin and Wallace proposed natural selection in 1858. Evolution explains the diversity and common ancestry of all life.",
        "climate change": "Climate change refers to long-term shifts in global temperatures driven primarily by human greenhouse gas emissions (CO2, methane). The greenhouse effect traps heat, raising average temperatures. Consequences: sea level rise, extreme weather, ecosystem disruption. Mitigation: reduce emissions. Adaptation: adjust to inevitable changes.",
        # ---- Everyday Topics ----
        "kitchen": "A kitchen is the room used for preparing and cooking food. It typically contains a stove, oven, microwave, refrigerator, sink, countertops, and storage cabinets. Kitchen design often follows the 'work triangle'—efficient placement of the sink, stove, and refrigerator. Modern kitchens also serve as social and gathering spaces.",
        "cooking": "Cooking is preparing food using heat or other methods to make it safe, palatable, and digestible. Methods include boiling, frying, baking, grilling, roasting, and steaming. The Maillard reaction and caramelization develop flavor when food browns. Key skills: knife work, heat control, seasoning, and timing multiple components.",
        "coffee": "Coffee is a brewed drink from roasted coffee beans containing caffeine, which stimulates the central nervous system. Brewing methods: espresso, drip/filter, French press, cold brew. Flavor depends on bean origin, roast level, grind size, water temperature, and brew time. It's the world's most popular psychoactive beverage.",
        "exercise": "Exercise is physical activity that maintains or improves fitness. Aerobic exercise (running, cycling) improves cardiovascular health; strength training (weights) builds muscle and bone density; flexibility training (yoga) improves range of motion. The WHO recommends 150+ minutes of moderate aerobic activity per week for adults.",
        "sleep": "Sleep is a recurring rest state essential for cognitive function, immune health, and memory consolidation. Adults typically need 7–9 hours. Sleep cycles through non-REM stages and REM (dreaming). Chronic deprivation impairs cognition and mental health. Good sleep hygiene: consistent schedule, dark/cool room, limit screens before bed.",
        "money": "Money is a medium of exchange serving as unit of account, store of value, and means of deferred payment. Forms: banknotes, coins, digital balances. Central banks manage money supply to control inflation. Personal finance involves budgeting, saving, investing, and managing debt. Compound interest powerfully amplifies both savings and debt.",
        "internet": "The internet is a global network of interconnected computers using TCP/IP. It carries email, web, streaming, and messaging traffic. The World Wide Web (websites/hyperlinks) runs on top of it. DNS translates domain names to IP addresses. The internet has transformed commerce, communication, and access to information.",
        "car": "A car is a wheeled motor vehicle for transportation. Most use internal combustion engines (gasoline/diesel); electric vehicles (EVs) use battery-powered motors. Key systems: engine, transmission, brakes, suspension, steering. EVs offer lower operating costs and zero direct emissions. The car transformed urban planning and the global economy.",
        "water": "Water (H2O) is essential for all known life, covering 71% of Earth's surface and making up ~60% of the human body. It's an excellent solvent for biochemical reactions. The water cycle (evaporation, condensation, precipitation) continuously redistributes freshwater. Over 2 billion people lack safe drinking water.",
        "weather": "Weather is short-term atmospheric conditions at a specific place—temperature, humidity, precipitation, wind, and cloudiness. Driven by uneven solar heating, Earth's rotation, and the water cycle. Meteorologists use sensors, satellites, and numerical models to forecast it. Weather differs from climate, which is the long-term average.",
        "music": "Music is organized sound communicating emotion through melody, rhythm, harmony, and timbre. Instrument categories: chordophones (strings), aerophones (wind), membranophones (drums), idiophones (percussion), electrophones (electronic). Music affects mood, memory, and physical arousal. Streaming platforms have transformed music distribution and discovery.",
        "book": "A book records information as text or images bound together. Formats range from ancient papyrus scrolls to modern print and e-books. Books serve as vehicles for literature, education, reference, and entertainment. E-books and audiobooks have expanded access and convenience significantly.",
        # ---- History / Society ----
        "democracy": "Democracy vests power in the people, exercised directly or through elected representatives. Key principles: free and fair elections, civil liberties, separation of powers, rule of law, majority rule with minority rights. Forms: representative (most common) and direct (referendums). Democratic systems vary widely in their specific structures.",
        "world war 2": "World War II (1939–1945) was a global conflict triggered by Nazi Germany's invasion of Poland. Key events: the Holocaust (6 million Jews murdered), D-Day, the Pacific theater, and atomic bombings of Hiroshima and Nagasaki. ~70–85 million people died, making it history's deadliest conflict. It reshaped the global order and created the United Nations.",
        "capitalism": "Capitalism is an economic system where private individuals or corporations own production means and operate for profit. Prices and production are coordinated by markets. Features: private property, voluntary exchange, wage labor, capital accumulation. Most modern economies are mixed—combining markets with government regulation and social programs.",
    }

    def _generate_rule_based(self, prompt: str) -> str:
        """Generate responses from the knowledge base or smart fallback."""
        import re as _re
        p = prompt.lower().strip()

        # Identity and social responses
        if _re.search(r'\b(who are you|your name|what are you)\b', p):
            return "I'm Dabba, a personal AI assistant built by Hasheem. I can explain AI and programming concepts, answer general knowledge questions, read files, and run shell commands. What would you like to know?"
        if _re.search(r'\b(hi|hello|hey|howdy)\b', p):
            return "Hey there! I'm Dabba AI. Ask me anything — AI concepts, programming, science, everyday topics, or let me explore files for you."
        if _re.search(r'\bhow are you\b', p):
            return "Running smoothly, thanks! What can I help you with?"
        if _re.search(r'\b(thanks|thank you)\b', p):
            return "You're welcome! Feel free to ask anything else."
        if _re.search(r'\b(bye|goodbye|see you)\b', p):
            return "Goodbye! Come back anytime."
        if _re.search(r'\bhelp\b', p) and len(p) < 15:
            return "I can help with: AI and ML concepts, programming topics, general science, everyday questions, reading files, and running shell commands. Just ask!"

        # Match knowledge base (longest key wins to avoid partial matches)
        kb = self._KNOWLEDGE
        matched_key = None
        for key in sorted(kb.keys(), key=len, reverse=True):
            if key in p:
                matched_key = key
                break
        if matched_key:
            return kb[matched_key]

        # Extract topic from "what is X", "explain X", "tell me about X"
        topic_match = _re.search(
            r'(?:what is|what are|explain|define|tell me about|describe|how does|how do)\s+(?:a |an |the )?(.+?)(?:\?|$)',
            p,
        )
        if topic_match:
            extracted = topic_match.group(1).strip().rstrip('?.!')
            # Try the extracted topic against knowledge base
            for key in sorted(kb.keys(), key=len, reverse=True):
                if key in extracted or extracted in key:
                    return kb[key]
            # Unknown topic — give a specific, honest response
            return (
                f"I don't have specific information about '{extracted}' in my current knowledge base. "
                f"I can answer questions about AI, machine learning, programming, science, and many everyday topics. "
                f"Try asking: 'What is machine learning?' or 'What is a kitchen?' for example."
            )

        # Longer inputs
        if len(p) > 150:
            return "That's quite detailed! Could you focus on one specific question? I can give a more thorough answer that way."

        # Default
        return (
            "I'm Dabba AI. I can explain AI/ML concepts, answer general knowledge questions, "
            "read files, and run shell commands. Try asking: 'What is machine learning?' or 'What is a kitchen?'"
        )

    def _detect_tool_call(self, prompt: str) -> str:
        """Return a <tool_call> block if the prompt needs a tool, else empty string."""
        import json as _json
        import re as _re

        p = prompt.strip()
        pl = p.lower()

        # --- file read ---
        for pat in [
            r"(?:read|show|cat|open|view|display)\s+(?:file\s+)?['\"]?([^\s'\"]+\.[^\s'\"]+)['\"]?",
            r"(?:what(?:'s| is) in|contents? of)\s+['\"]?([^\s'\"]+\.[^\s'\"]+)['\"]?",
        ]:
            m = _re.search(pat, pl)
            if m:
                path = m.group(1)
                return '<tool_call>' + _json.dumps({"name": "file_read", "arguments": {"path": path}}) + '</tool_call>'

        # --- folder/directory capability questions ---
        if _re.search(r"what\s+(?:does|can|is|are)\s+(?:this|the)?\s*(?:folder|dir(?:ectory)?|project|repo|codebase)", pl) or \
           _re.search(r"what\s+(?:this|the)\s+(?:folder|dir(?:ectory)?|project)\s+(?:can|does|do)", pl):
            return '<tool_call>' + _json.dumps({"name": "file_list", "arguments": {"path": "."}}) + '</tool_call>'

        # --- file list / ls ---
        for pat in [
            r"(?:list|ls|show)\s+(?:files?|dir(?:ectory)?|folder)?\s*(?:in\s+)?['\"]?([^\s'\"]*)['\"]?",
            r"what files",
            r"files? in",
        ]:
            m = _re.search(pat, pl)
            if m:
                try:
                    path = m.group(1).strip()
                except IndexError:
                    path = ""
                if not path or path in ("this", "the", "my", "current"):
                    path = "."
                return '<tool_call>' + _json.dumps({"name": "file_list", "arguments": {"path": path}}) + '</tool_call>'

        # --- shell / run command ---
        shell_pats = [
            r"^(?:run|execute|bash|shell|cmd)\s+(.+)",
            r"^\$\s*(.+)",
        ]
        for pat in shell_pats:
            m = _re.match(pat, pl)
            if m:
                cmd = m.group(1).strip()
                return '<tool_call>' + _json.dumps({"name": "shell_exec", "arguments": {"command": cmd}}) + '</tool_call>'

        # Plain shell commands (start with common shell words)
        if _re.match(r"^(ls|pwd|echo|mkdir|cp|mv|rm|grep|find|cat|head|tail|python|pip|git|npm|node)\b", pl):
            return '<tool_call>' + _json.dumps({"name": "shell_exec", "arguments": {"command": p}}) + '</tool_call>'

        # --- file write ---
        m = _re.search(r"(?:write|create|save)\s+(?:a\s+)?file\s+['\"]?([^\s'\"]+)['\"]?", pl)
        if m:
            path = m.group(1)
            return '<tool_call>' + _json.dumps({"name": "file_write", "arguments": {"path": path, "content": ""}}) + '</tool_call>'

        # --- search files ---
        m = _re.search(r"(?:search|find|grep)\s+(?:for\s+)?['\"]?([^'\"]+)['\"]?\s+in\s+files?", pl)
        if m:
            pattern = m.group(1).strip()
            return '<tool_call>' + _json.dumps({"name": "file_search", "arguments": {"pattern": f"*{pattern}*"}}) + '</tool_call>'

        return ""

    def _summarize_tool_results(self, original_request: str, tool_results: List[str]) -> str:
        """Generate a natural-language summary of tool execution results."""
        if not tool_results:
            return "Done."

        MAX_SHOWN = 3000
        combined = "\n\n".join(tool_results)
        shown = combined if len(combined) <= MAX_SHOWN else combined[:MAX_SHOWN] + "\n… (truncated)"

        if "file_read" in combined or "Tool 'file_read'" in combined:
            return f"Here is the file content:\n\n{shown}"
        if "file_list" in combined or "Tool 'file_list'" in combined:
            return f"Here are the files:\n\n{shown}"
        if "shell_exec" in combined or "Tool 'shell_exec'" in combined:
            return f"Command output:\n\n{shown}"
        if "FAILED" in combined or "Error:" in combined:
            return f"That didn't fully succeed:\n\n{shown}"

        return f"Here are the results:\n\n{shown}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler for startup and shutdown.

    Loads models on startup and cleans up on shutdown.
    """
    config = app.state.config
    engine = app.state.model_engine

    if engine and config:
        try:
            engine.load()
            app.state.logger.info(f"Model engine loaded")
        except Exception as e:
            app.state.logger.warning(f"Could not load model: {e}")

    yield

    app.state.logger.info("Server shutting down")


def create_app(
    config: Optional[ApiConfig] = None,
    model_engine: Optional[ModelEngine] = None,
    embedding_engine: Optional[object] = None,
    available_models: Optional[List[str]] = None,
    title: Optional[str] = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        config: API server configuration.
        model_engine: Optional model engine for generation.
        embedding_engine: Optional embedding engine.
        available_models: List of available model names.
        title: Optional app title override.

    Returns:
        Configured FastAPI application.
    """
    if config is None:
        config = ApiConfig()

    app = FastAPI(
        title=title or "dabba API",
        description="OpenAI-compatible inference API for dabba language models",
        version="0.1.0",
        lifespan=lifespan,
    )

    import logging as py_logging
    logger = py_logging.getLogger("dabba.api")
    logger.setLevel(getattr(py_logging, config.log_level.upper()))

    app.state.config = config
    app.state.logger = logger

    app.state.model_engine = model_engine or ModelEngine()
    app.state.embedding_engine = embedding_engine

    auth = None
    if config.auth_enabled:
        auth = ApiKeyAuth(
            api_keys=config.api_keys,
            config=config,
        )
    app.state.auth = auth

    rate_limiter = None
    if config.rate_limit_enabled:
        rate_limiter = RateLimiter(
            requests_per_minute=config.rate_limit_requests_per_minute,
            burst=config.rate_limit_burst,
        )
    app.state.rate_limiter = rate_limiter

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log incoming requests and their durations."""
        if not config.log_requests:
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        logger.info(
            f"{request.method} {request.url.path} "
            f"{response.status_code} {duration:.3f}s"
        )
        return response

    @app.get("/health")
    async def health_check():
        """Health check endpoint for monitoring."""
        return {
            "status": "healthy",
            "version": "0.1.0",
            "model_loaded": app.state.model_engine.model is not None,
        }

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Custom exception handler for HTTP errors."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": exc.detail,
                    "type": "api_error",
                    "code": exc.status_code,
                }
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """General exception handler for unhandled errors."""
        logger.error(f"Unhandled error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": "Internal server error",
                    "type": "internal_error",
                    "code": 500,
                }
            },
        )

    models = available_models or config.available_models

    app.include_router(create_chat_router(
        model_engine=app.state.model_engine,
        auth=auth,
        rate_limiter=rate_limiter,
    ))

    app.include_router(create_embedding_router(
        embedding_engine=app.state.embedding_engine,
        auth=auth,
        rate_limiter=rate_limiter,
    ))

    app.include_router(create_model_router(
        available_models=models,
        auth=auth,
    ))

    from dabba.api.execution_endpoints import create_execution_router
    app.include_router(create_execution_router(auth=auth, rate_limiter=rate_limiter))

    # Agent streaming endpoint for the VSCode extension (tool-using agent loop)
    try:
        from dabba.api.agent_endpoints import create_agent_router
        app.include_router(create_agent_router())
    except Exception as _agent_exc:
        logger.warning(f"Agent endpoints unavailable: {_agent_exc}")

    # Voice input transcription for the VSCode extension's mic button
    try:
        from dabba.api.audio_endpoints import create_audio_router
        app.include_router(create_audio_router())
    except Exception as _audio_exc:
        logger.warning(f"Audio endpoints unavailable: {_audio_exc}")

    # Image generation (proxies to a key-configured image provider, e.g. OpenAI)
    try:
        from dabba.api.image_endpoints import create_image_router
        app.include_router(create_image_router())
    except Exception as _image_exc:
        logger.warning(f"Image endpoints unavailable: {_image_exc}")

    # Server-side conversation storage for the web frontend (SQLite, scoped by user_id)
    try:
        from dabba.api.conversations_endpoints import create_conversations_router
        app.include_router(create_conversations_router())
    except Exception as _conv_exc:
        logger.warning(f"Conversation endpoints unavailable: {_conv_exc}")

    # Text-to-speech for spoken replies (offline Piper TTS)
    try:
        from dabba.api.tts_endpoints import create_tts_router
        app.include_router(create_tts_router())
    except Exception as _tts_exc:
        logger.warning(f"Speech endpoints unavailable: {_tts_exc}")

    @app.get("/")
    async def root():
        """Root endpoint with API information."""
        return {
            "name": "dabba API",
            "version": "0.1.0",
            "endpoints": {
                "chat": "/v1/chat/completions",
                "embeddings": "/v1/embeddings",
                "models": "/v1/models",
                "health": "/health",
            },
            "docs": "/docs",
        }

    return app


def run_server(
    config_path: Optional[str] = None,
    model_path: Optional[str] = None,
    host: str = "0.0.0.0",
    port: int = 8080,
    reload: bool = False,
):
    """
    Run the dabba API server.

    Args:
        config_path: Path to server configuration YAML.
        model_path: Path to the model to load.
        host: Server host address.
        port: Server port.
        reload: Enable hot reload (development only).
    """
    import uvicorn

    if config_path and os.path.exists(config_path):
        import yaml
        with open(config_path) as f:
            data = yaml.safe_load(f)
        config = ApiConfig(**data.get("api", {}))
    else:
        config = ApiConfig(host=host, port=port)

    model_engine = None
    if model_path:
        model_engine = ModelEngine(model_path=model_path)

    app = create_app(config=config, model_engine=model_engine)

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        workers=config.workers,
        reload=reload,
        log_level=config.log_level,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the dabba API server")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--model", type=str, help="Path to model")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    run_server(
        config_path=args.config,
        model_path=args.model,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
