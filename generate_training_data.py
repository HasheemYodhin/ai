#!/usr/bin/env python3
"""
Generate comprehensive training data for Dabba.

Produces varied, conversational training examples covering:
  - AI/ML/CS core knowledge with multiple question phrasings per topic
  - General world knowledge (everyday topics, science, history, etc.)
  - Out-of-scope graceful-decline examples
  - Multi-turn conversation snippets
  - Project Gutenberg public-domain text

Saves incrementally so partial results survive timeouts.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

OUTPUT_FILE = Path("data/train/dabba_training_data.txt")
LOG_FILE = Path("data/collection_log.json")


# ============================================================
# KNOWLEDGE BASE
# Each entry: topic_key -> { "answer": str, "tags": [str] }
# question variants are generated automatically below.
# ============================================================

KNOWLEDGE_BASE = {
    # ---- AI / ML ----
    "artificial intelligence": {
        "answer": "Artificial intelligence (AI) is the broad field of computer science focused on creating systems that can perform tasks requiring human intelligence, such as learning, reasoning, perception, and decision-making. It includes subfields like machine learning, deep learning, natural language processing, and computer vision. AI is applied across healthcare, finance, transportation, and virtually every industry.",
        "tags": ["ai", "ml"],
    },
    "machine learning": {
        "answer": "Machine learning is a subset of AI where computers learn from data without being explicitly programmed for every scenario. A model analyzes training data, identifies patterns, and uses them to make predictions on new data. The three main paradigms are supervised learning (labeled examples), unsupervised learning (finding hidden patterns), and reinforcement learning (learning through rewards). Common algorithms include decision trees, neural networks, and support vector machines.",
        "tags": ["ai", "ml"],
    },
    "deep learning": {
        "answer": "Deep learning uses neural networks with many layers to model complex patterns. The word 'deep' refers to multiple hidden layers, each learning progressively more abstract features. Early layers detect simple patterns like edges; deeper layers recognize complex concepts like faces or meanings. Deep learning powers image recognition, speech assistants, and large language models. Key architectures include CNNs (for images), RNNs (for sequences), and Transformers (for language).",
        "tags": ["ai", "ml"],
    },
    "neural network": {
        "answer": "A neural network is a computational model inspired by the brain. It consists of layers of nodes (neurons). Each connection has a weight. During training, the network adjusts weights via backpropagation to minimize prediction error. An input layer receives data, hidden layers transform it, and the output layer produces the result. With enough layers and data, neural networks can approximate virtually any function.",
        "tags": ["ai", "ml"],
    },
    "transformer": {
        "answer": "The Transformer is a neural network architecture introduced in 2017 ('Attention Is All You Need'). It replaced recurrence with self-attention, allowing every token to directly attend to every other token in the sequence. This enables parallel computation and captures long-range dependencies efficiently. Transformers are the foundation of BERT, GPT, Llama, and most modern large language models.",
        "tags": ["ai", "ml"],
    },
    "attention mechanism": {
        "answer": "The attention mechanism lets a model focus on relevant parts of the input when processing each element. For each token, it computes Query, Key, and Value vectors. Attention weights are softmax-normalized dot products of Query and Key; the output is a weighted sum of Values. Multi-head attention runs this in parallel with different learned projections, capturing diverse relationships.",
        "tags": ["ai", "ml"],
    },
    "large language model": {
        "answer": "Large language models (LLMs) are transformer-based neural networks trained on trillions of tokens of text to predict the next token. With billions of parameters, they develop language understanding, world knowledge, and reasoning. Examples include GPT-4, Claude, Llama, and Gemini. They can generate text, translate, summarize, write code, and answer questions. LLMs can be fine-tuned or used via prompt engineering for specific tasks.",
        "tags": ["ai", "ml"],
    },
    "retrieval-augmented generation": {
        "answer": "Retrieval-Augmented Generation (RAG) combines information retrieval with language model generation. Instead of relying solely on the model's internal knowledge, RAG retrieves relevant documents from a database and feeds them as context to the LLM. Benefits: reduces hallucinations, enables answering questions about private or recent data, and allows citing sources. A typical RAG pipeline includes an embedding model, a vector store, and a generation model.",
        "tags": ["ai", "ml"],
    },
    "rag": {
        "answer": "RAG stands for Retrieval-Augmented Generation. It is a technique where a language model retrieves relevant documents from a knowledge base before generating a response. This grounds the answer in factual sources, reduces hallucinations, and allows the model to answer questions about data it wasn't trained on. RAG systems use vector databases for efficient semantic search.",
        "tags": ["ai", "ml"],
    },
    "fine-tuning": {
        "answer": "Fine-tuning adapts a pre-trained model to a specific task or domain by continuing training on a smaller, task-specific dataset. It uses a lower learning rate to preserve pre-trained knowledge while specializing behavior. Methods include full fine-tuning (updating all weights), LoRA (updating small adapter matrices), and prompt tuning (learning soft prompts). Fine-tuning requires much less data and compute than training from scratch.",
        "tags": ["ai", "ml"],
    },
    "embeddings": {
        "answer": "Embeddings are dense numerical vectors that represent data (words, sentences, images) in a continuous space. Similar items have similar vectors, enabling mathematical operations on meaning. Word2Vec, GloVe, and contextual embeddings from BERT/GPT learn these representations during training. Embeddings power semantic search, recommendation systems, clustering, and are the input representation for neural networks.",
        "tags": ["ai", "ml"],
    },
    "backpropagation": {
        "answer": "Backpropagation computes gradients of the loss function with respect to each weight in a neural network using the chain rule of calculus. In the forward pass, data flows through the network to produce a prediction. In the backward pass, the error gradient flows backward, telling each weight how much it contributed to the error. Optimization algorithms then update weights in the direction that reduces loss.",
        "tags": ["ai", "ml"],
    },
    "gradient descent": {
        "answer": "Gradient descent is an optimization algorithm that iteratively adjusts model parameters to minimize the loss function. At each step, parameters move in the direction opposite to the gradient (steepest ascent). Variants include batch gradient descent (full dataset), stochastic gradient descent (single sample), and mini-batch gradient descent. Adaptive optimizers like Adam adjust per-parameter learning rates based on gradient history.",
        "tags": ["ai", "ml"],
    },
    "nlp": {
        "answer": "Natural Language Processing (NLP) is the AI field focused on enabling computers to understand and generate human language. Key tasks include sentiment analysis, machine translation, question answering, named entity recognition, text summarization, and part-of-speech tagging. Modern NLP is dominated by transformer-based models like BERT, GPT, and T5 that learn rich language representations from massive text corpora.",
        "tags": ["ai", "ml"],
    },
    "reinforcement learning": {
        "answer": "Reinforcement learning trains an agent to make decisions by interacting with an environment and receiving rewards or penalties. The agent learns a policy that maximizes cumulative reward. Key algorithms include Q-learning, deep Q-networks (DQN), and policy gradient methods. RL has achieved superhuman performance in chess, Go, and video games, and is used in robotics and recommendation systems.",
        "tags": ["ai", "ml"],
    },
    "vector database": {
        "answer": "A vector database stores and indexes high-dimensional embeddings for efficient similarity search. Unlike traditional databases that match exact values, vector DBs find semantically similar items using approximate nearest neighbor (ANN) algorithms like HNSW. They power RAG systems, semantic search, and recommendation engines. Popular options include Pinecone, Weaviate, Chroma, Milvus, and pgvector.",
        "tags": ["ai", "ml"],
    },
    "prompt engineering": {
        "answer": "Prompt engineering is the practice of designing inputs to large language models to get better outputs. Techniques include zero-shot prompting, few-shot prompting (providing examples), chain-of-thought (asking for step-by-step reasoning), and structured formatting. Good prompts specify context, role, output format, and constraints. It is a key skill for using LLMs effectively without modifying the model itself.",
        "tags": ["ai", "ml"],
    },
    "tokenization": {
        "answer": "Tokenization breaks text into smaller units (tokens) for processing by language models. Subword tokenization algorithms like Byte-Pair Encoding (BPE) split text into common subwords, balancing vocabulary size and coverage. Special tokens like [CLS], [SEP], and [PAD] serve structural roles. A typical LLM processes roughly 1 token per 4 characters of English text.",
        "tags": ["ai", "ml"],
    },

    # ---- CS / Programming ----
    "api": {
        "answer": "An API (Application Programming Interface) is a set of rules that lets software applications communicate with each other. REST APIs use HTTP methods (GET, POST, PUT, DELETE) and typically return JSON data. APIs allow teams to build modular systems where services expose capabilities without revealing their internals. Good API design includes clear endpoints, versioning, authentication, rate limiting, and documentation.",
        "tags": ["cs"],
    },
    "git": {
        "answer": "Git is a distributed version control system that tracks changes to files and enables collaboration. Every developer has a full copy of the repository. Key concepts: commits (snapshots), branches (independent lines of development), merges, and pull requests. Common commands: git clone, git add, git commit, git push, git pull, git branch, git merge, git log. Platforms like GitHub and GitLab host Git repositories.",
        "tags": ["cs"],
    },
    "docker": {
        "answer": "Docker is a platform for packaging applications into containers—lightweight, isolated environments that include the application code, runtime, and dependencies. Containers share the host OS kernel, making them faster and smaller than virtual machines. Docker images are built from Dockerfiles, stored in registries like Docker Hub, and run as containers. Docker Compose manages multi-container apps. Kubernetes orchestrates containers at scale.",
        "tags": ["cs"],
    },
    "sql": {
        "answer": "SQL (Structured Query Language) is the standard language for relational databases. It uses SELECT to query data, INSERT/UPDATE/DELETE to modify it, and CREATE/ALTER/DROP to manage schema. JOINs combine data from multiple tables. Aggregations (COUNT, SUM, AVG, GROUP BY) summarize data. SQL databases include PostgreSQL, MySQL, SQLite, and SQL Server.",
        "tags": ["cs"],
    },
    "python": {
        "answer": "Python is a high-level, dynamically typed programming language known for its readable syntax and large ecosystem. It is widely used in data science, machine learning, web development, scripting, and automation. Key features include list comprehensions, generators, decorators, first-class functions, and a rich standard library. Popular frameworks: Django and Flask for web, NumPy/Pandas for data, PyTorch/TensorFlow for ML.",
        "tags": ["cs"],
    },
    "hash table": {
        "answer": "A hash table maps keys to values using a hash function to compute an array index. Ideal case: O(1) average time for lookup, insert, and delete. Collisions (multiple keys mapping to the same index) are resolved via chaining (linked list at each slot) or open addressing (probing for the next free slot). Python's dict, JavaScript's Map, and Java's HashMap are implemented as hash tables.",
        "tags": ["cs"],
    },
    "object-oriented programming": {
        "answer": "Object-oriented programming (OOP) organizes code around objects that bundle data (attributes) and behavior (methods). Four pillars: encapsulation (hiding internal state), inheritance (subclasses reuse parent class code), polymorphism (objects respond to the same interface differently), and abstraction (hiding complexity). OOP languages include Python, Java, C++, and C#. Design patterns like Singleton, Factory, and Observer are common OOP solutions.",
        "tags": ["cs"],
    },
    "microservices": {
        "answer": "Microservices is an architecture where an application is split into small, independent services, each focused on one business capability. Services communicate via APIs or message queues, can use different languages and databases, and deploy independently. Benefits: scalability, team autonomy, fault isolation. Challenges: distributed system complexity, data consistency, and operational overhead. Often paired with Docker, Kubernetes, and CI/CD pipelines.",
        "tags": ["cs"],
    },

    # ---- General Science ----
    "photosynthesis": {
        "answer": "Photosynthesis is the process by which plants, algae, and some bacteria convert sunlight, carbon dioxide, and water into glucose and oxygen. It occurs mainly in chloroplasts, using chlorophyll to absorb light energy. The light reactions split water molecules and produce ATP and NADPH. The Calvin cycle uses that energy to fix CO2 into sugars. Photosynthesis is the foundation of most food chains and produces the oxygen in Earth's atmosphere.",
        "tags": ["science", "biology"],
    },
    "dna": {
        "answer": "DNA (deoxyribonucleic acid) is the molecule that carries genetic information in living organisms. It is a double helix made of nucleotide base pairs: adenine pairs with thymine, and guanine pairs with cytosine. Genes are segments of DNA that encode proteins. DNA replication copies the genome before cell division. Mutations in DNA can cause diseases or drive evolution. The Human Genome Project mapped all ~3 billion base pairs in the human genome.",
        "tags": ["science", "biology"],
    },
    "gravity": {
        "answer": "Gravity is the force of attraction between objects with mass. On Earth, it accelerates objects at 9.8 m/s². Newton described gravity as a force proportional to mass and inversely proportional to distance squared. Einstein's general relativity describes gravity as the curvature of spacetime caused by mass and energy. Gravity governs planetary orbits, tides, the structure of stars, and the large-scale structure of the universe.",
        "tags": ["science", "physics"],
    },
    "electricity": {
        "answer": "Electricity is the flow of electric charge, typically electrons, through a conductor. Voltage (measured in volts) is the electrical potential difference. Current (amperes) is the rate of charge flow. Resistance (ohms) opposes current. Ohm's Law states V = IR. Alternating current (AC) reverses direction periodically; direct current (DC) flows in one direction. Electricity powers virtually all modern technology.",
        "tags": ["science", "physics"],
    },
    "evolution": {
        "answer": "Evolution is the process of change in the heritable characteristics of biological populations over successive generations. Natural selection—where organisms with traits better suited to their environment survive and reproduce more—drives adaptation. Genetic variation arises from mutations and sexual reproduction. Darwin and Wallace independently proposed natural selection in 1858. Evolution explains the diversity of life and the common ancestry of all living organisms.",
        "tags": ["science", "biology"],
    },
    "climate change": {
        "answer": "Climate change refers to long-term shifts in global temperatures and weather patterns, primarily caused since the 20th century by human activities that release greenhouse gases like CO2 and methane. The greenhouse effect traps heat in the atmosphere, raising average temperatures. Consequences include sea level rise, more extreme weather events, ecosystem disruption, and threats to food and water security. Mitigation involves reducing emissions; adaptation involves adjusting to inevitable changes.",
        "tags": ["science", "environment"],
    },

    # ---- Everyday Topics ----
    "kitchen": {
        "answer": "A kitchen is the room in a home or building used for preparing and cooking food. It typically contains cooking appliances (stove, oven, microwave), food storage (refrigerator, freezer, cabinets, pantry), a sink for washing, countertops for food preparation, and small appliances like a toaster or coffee maker. Kitchen design focuses on the 'work triangle'—efficient placement of the sink, stove, and refrigerator. Modern kitchens also serve as social spaces.",
        "tags": ["everyday"],
    },
    "cooking": {
        "answer": "Cooking is the process of preparing food using heat or other methods to make it safe, palatable, and digestible. Common methods include boiling, frying, baking, grilling, roasting, and steaming. Cooking breaks down cell walls, kills bacteria, and develops flavors through Maillard reactions and caramelization. Key skills include knife work, understanding heat control, seasoning, and timing multiple components to be ready together.",
        "tags": ["everyday"],
    },
    "coffee": {
        "answer": "Coffee is a brewed drink made from roasted coffee beans. It contains caffeine, which stimulates the central nervous system and reduces fatigue. Common brewing methods include espresso (high-pressure extraction), drip/filter, French press, and cold brew. The flavor depends on bean origin, roast level, grind size, water temperature, and brew time. Coffee is the world's most popular psychoactive beverage and a major global commodity.",
        "tags": ["everyday"],
    },
    "exercise": {
        "answer": "Exercise is physical activity that improves or maintains physical fitness and health. Types include aerobic exercise (running, cycling, swimming—improves cardiovascular health), strength training (weights, resistance bands—builds muscle and bone density), and flexibility training (yoga, stretching). Regular exercise reduces risk of heart disease, diabetes, depression, and obesity. The WHO recommends at least 150 minutes of moderate aerobic activity per week for adults.",
        "tags": ["everyday", "health"],
    },
    "sleep": {
        "answer": "Sleep is a natural, recurring state of rest during which consciousness is altered and the body undergoes repair and consolidation of memories. Adults typically need 7–9 hours per night. Sleep cycles through non-REM stages (light and deep sleep) and REM (rapid eye movement) sleep, during which dreaming occurs. Chronic sleep deprivation impairs cognition, immune function, and mental health. Good sleep hygiene includes consistent schedules and limiting screens before bed.",
        "tags": ["everyday", "health"],
    },
    "money": {
        "answer": "Money is a medium of exchange used to buy goods and services. It functions as a unit of account (measuring value), store of value (holding purchasing power over time), and means of deferred payment. Modern money includes banknotes, coins, and digital balances. Central banks control money supply to manage inflation. Personal finance involves budgeting, saving, investing, and managing debt. Compound interest is a powerful force in both saving and borrowing.",
        "tags": ["everyday"],
    },
    "internet": {
        "answer": "The internet is a global network of interconnected computers that communicate using standardized protocols (TCP/IP). It carries traffic for email, web browsing, streaming, messaging, and more. The World Wide Web (websites and hyperlinks) is a service that runs on the internet. Key infrastructure includes routers, undersea cables, data centers, and the Domain Name System (DNS) that translates domain names to IP addresses. The internet has transformed communication, commerce, and access to information.",
        "tags": ["everyday", "cs"],
    },
    "car": {
        "answer": "A car (automobile) is a wheeled motor vehicle used for transportation. Most cars use internal combustion engines powered by gasoline or diesel, though electric vehicles (EVs) with battery-powered motors are growing rapidly. Key systems include the engine, transmission, brakes, suspension, and steering. The invention of the car in the late 19th century fundamentally changed transportation, urban planning, and the economy. EVs offer lower operating costs and zero direct emissions.",
        "tags": ["everyday"],
    },
    "water": {
        "answer": "Water (H2O) is a transparent, tasteless liquid essential for all known life. It covers about 71% of Earth's surface and makes up roughly 60% of the human body. Water is an excellent solvent, critical for biochemical reactions. It exists as liquid, solid (ice), and gas (water vapor). The water cycle (evaporation, condensation, precipitation) continuously redistributes freshwater. Access to clean water is a fundamental human need; over 2 billion people lack safe drinking water.",
        "tags": ["science", "everyday"],
    },
    "weather": {
        "answer": "Weather refers to the short-term atmospheric conditions at a specific place and time—temperature, humidity, precipitation, wind speed, and cloudiness. It is driven by uneven heating of Earth's surface, the rotation of the planet, and the water cycle. Weather patterns are studied by meteorologists using sensors, satellites, and numerical models. Weather differs from climate: climate is the long-term average of weather conditions over decades.",
        "tags": ["science", "everyday"],
    },
    "music": {
        "answer": "Music is organized sound that communicates emotion and expression through melody, rhythm, harmony, and timbre. It exists across all known human cultures. Instruments fall into categories: chordophones (strings), aerophones (wind), membranophones (drums), idiophones (percussion), and electrophones (electronic). Music affects mood, memory, and physical arousal. Streaming platforms have transformed how music is distributed and discovered.",
        "tags": ["everyday", "arts"],
    },
    "book": {
        "answer": "A book is a medium for recording information in the form of writing or images, typically composed of pages bound together with a cover. Books have existed since ancient times, from papyrus scrolls to modern print and digital formats. They serve as vehicles for literature, education, reference, and entertainment. Libraries and publishing houses are central to the distribution of books. E-books and audiobooks have expanded access and convenience.",
        "tags": ["everyday", "arts"],
    },

    # ---- History / Society ----
    "democracy": {
        "answer": "Democracy is a system of government in which power is vested in the people, who exercise it directly or through elected representatives. Representative democracies hold free and fair elections, protect civil liberties, and maintain separation of powers. Direct democracy allows citizens to vote on laws themselves. Key principles include majority rule with minority rights, rule of law, freedom of speech and press, and independent judiciary. Modern democratic systems vary widely in their specific structures.",
        "tags": ["society"],
    },
    "world war 2": {
        "answer": "World War II (1939–1945) was a global conflict involving most of the world's nations. It was triggered by Nazi Germany's invasion of Poland and ended with Allied victory in Europe and Japan. Key events include the Holocaust (systematic murder of 6 million Jews and millions of others), the D-Day landings, the Pacific theater, and the atomic bombings of Hiroshima and Nagasaki. An estimated 70–85 million people died, making it the deadliest conflict in human history. It reshaped the global order and led to the United Nations.",
        "tags": ["history"],
    },
    "capitalism": {
        "answer": "Capitalism is an economic system in which private individuals or corporations own the means of production and operate for profit. Prices and production are coordinated through markets. Key features include private property, voluntary exchange, wage labor, and capital accumulation. It is the dominant economic system in most of the world. Critiques include inequality, market failures, and externalities like environmental damage. Mixed economies combine capitalist markets with government regulation and social programs.",
        "tags": ["society", "economics"],
    },
}


# ============================================================
# QUESTION VARIANT TEMPLATES
# Each template includes a {topic} placeholder.
# ============================================================

QUESTION_TEMPLATES = [
    "What is {topic}?",
    "What is {topic}",
    "Can you explain {topic}?",
    "Explain {topic}.",
    "Tell me about {topic}.",
    "How does {topic} work?",
    "Define {topic}.",
    "Give me an overview of {topic}.",
    "What do you know about {topic}?",
    "I want to learn about {topic}.",
    "What is {topic} and why does it matter?",
    "what is {topic}",
    "explain {topic}",
    "tell me about {topic}",
]


# ============================================================
# OUT-OF-SCOPE EXAMPLES
# Trains the model to gracefully decline and redirect.
# ============================================================

OUT_OF_SCOPE_PAIRS = [
    ("What is the stock price of Apple?",
     "I don't have access to real-time data like stock prices. For current prices, check a financial site like Yahoo Finance or Google Finance. I can help explain concepts like how stock markets work if that's useful."),
    ("What will the weather be tomorrow?",
     "I don't have access to real-time weather data. For a forecast, check a weather service like weather.com or a local meteorology app. I can explain how weather forecasting works if you're curious."),
    ("Who won the game last night?",
     "I don't have access to real-time sports scores. For live results, check ESPN, Google, or your team's official website. I'm happy to explain sports rules or history if that helps."),
    ("Can you order a pizza for me?",
     "I can't place orders or take actions outside this conversation. For pizza, apps like DoorDash, Uber Eats, or your local pizzeria's website are the way to go. Let me know if you have other questions I can actually help with."),
    ("What is my bank account balance?",
     "I don't have access to your personal accounts or any private data. Please check your bank's app or website directly. I can explain banking concepts or financial topics if helpful."),
    ("What is 2 + 2?",
     "2 + 2 equals 4. Simple arithmetic is straightforward — is there a more complex calculation or concept I can help with?"),
    ("What is the capital of France?",
     "The capital of France is Paris. It is also the country's largest city and cultural center. Is there more you'd like to know about France or European geography?"),
    ("How tall is Mount Everest?",
     "Mount Everest is the world's highest mountain, standing at 8,848.86 meters (29,031.7 feet) above sea level. It is located in the Himalayas on the border of Nepal and Tibet. The height was updated after a 2020 Chinese-Nepalese survey."),
    ("What is the meaning of life?",
     "That's one of humanity's oldest philosophical questions. Different traditions offer different answers: Aristotle said eudaimonia (flourishing through virtue), existentialists say we create our own meaning, and from a biological perspective life's 'purpose' is reproduction and survival. Many people find meaning through relationships, creativity, contribution, and personal growth. What's your perspective?"),
]


# ---- Conversation-style multi-turn examples ----

CONVERSATION_EXAMPLES = [
    [
        ("User", "Hi"),
        ("Dabba", "Hey there! I'm Dabba AI. I can explain AI and machine learning concepts, answer general knowledge questions, read files, run shell commands, and more. What would you like to know?"),
    ],
    [
        ("User", "What can you do?"),
        ("Dabba", "I can help with: explaining AI, ML, and programming concepts; answering general knowledge questions about science, history, and everyday topics; reading and exploring files in your project; running shell commands; and answering technical questions. What would you like to explore?"),
    ],
    [
        ("User", "What is machine learning?"),
        ("Dabba", "Machine learning is a subset of AI where computers learn patterns from data without being explicitly programmed. A model trains on examples, discovers statistical patterns, and uses them to make predictions on new data. The main paradigms are supervised learning (labeled data), unsupervised learning (finding hidden structure), and reinforcement learning (learning via rewards)."),
        ("User", "Can you give me an example?"),
        ("Dabba", "Sure! A spam filter is a classic supervised learning example. You train a model on thousands of emails labeled 'spam' or 'not spam'. The model learns which words and patterns correlate with spam. When a new email arrives, the model predicts whether it's spam based on those learned patterns — no explicit rules needed."),
    ],
    [
        ("User", "what is a kitchen"),
        ("Dabba", "A kitchen is the room used for preparing and cooking food. It typically has a stove, oven, refrigerator, sink, countertops, and storage cabinets. Modern kitchens are also social spaces. Kitchen design often follows the 'work triangle' principle, placing the sink, stove, and refrigerator in a triangle for efficient workflow."),
    ],
    [
        ("User", "explain rag"),
        ("Dabba", "RAG stands for Retrieval-Augmented Generation. Instead of relying only on a language model's internal knowledge, RAG first retrieves relevant documents from a knowledge base, then passes them as context to the LLM when generating a response. This reduces hallucinations, allows answering questions about private or recent data, and makes it possible to cite sources. It's widely used in enterprise AI applications."),
    ],
    [
        ("User", "what is a transformer in AI"),
        ("Dabba", "In AI, a Transformer is a neural network architecture introduced in 2017 that uses self-attention instead of recurrence. Every token in a sequence can directly attend to every other token, capturing long-range dependencies efficiently and enabling parallel computation. Transformers are the backbone of modern large language models like GPT, BERT, and Claude."),
        ("User", "how is it different from an RNN?"),
        ("Dabba", "RNNs process sequences step by step — each token depends on the previous hidden state, which creates a bottleneck and makes parallelism difficult. Transformers process the entire sequence at once using attention, making them much faster to train. Transformers also handle long-range dependencies better because attention directly connects any two positions, whereas RNNs struggle to carry information across many steps."),
    ],
]


# ============================================================
# Gutenberg books
# ============================================================

GUTENBERG_SOURCES = [
    ("https://www.gutenberg.org/cache/epub/5827/pg5827.txt", "The Art of War - Sun Tzu"),
    ("https://www.gutenberg.org/cache/epub/1342/pg1342.txt", "Pride and Prejudice - Jane Austen"),
    ("https://www.gutenberg.org/cache/epub/84/pg84.txt", "Frankenstein - Mary Shelley"),
    ("https://www.gutenberg.org/cache/epub/11/pg11.txt", "Alice in Wonderland - Lewis Carroll"),
    ("https://www.gutenberg.org/cache/epub/1661/pg1661.txt", "Sherlock Holmes - Arthur Conan Doyle"),
    ("https://www.gutenberg.org/cache/epub/2701/pg2701.txt", "Moby Dick - Herman Melville"),
    ("https://www.gutenberg.org/cache/epub/1260/pg1260.txt", "Jane Eyre - Charlotte Brontë"),
    ("https://www.gutenberg.org/cache/epub/5001/pg5001.txt", "Relativity - Albert Einstein"),
    ("https://www.gutenberg.org/cache/epub/1228/pg1228.txt", "Origin of Species - Charles Darwin"),
    ("https://www.gutenberg.org/cache/epub/30104/pg30104.txt", "Problems of Philosophy - Bertrand Russell"),
]

USER_AGENT = "DabbaAI/1.0 (educational training data collector)"


# ============================================================
# Generation helpers
# ============================================================

def generate_qa_lines(knowledge_base: dict, templates: list) -> list[str]:
    """
    For each topic, generate Q→A lines using every question template.
    Returns plain-text lines suitable for language model pre-training.
    """
    lines = []
    for topic_key, entry in knowledge_base.items():
        answer = entry["answer"]
        for template in templates:
            question = template.format(topic=topic_key)
            lines.append(f"Q: {question}\nA: {answer}")
        # Also add the bare answer as plain text for better coverage
        lines.append(answer)
    return lines


def generate_out_of_scope_lines(pairs: list) -> list[str]:
    lines = []
    for question, response in pairs:
        lines.append(f"Q: {question}\nA: {response}")
    return lines


def generate_conversation_lines(conversations: list) -> list[str]:
    lines = []
    for turns in conversations:
        parts = []
        for role, text in turns:
            parts.append(f"{role}: {text}")
        lines.append("\n".join(parts))
    return lines


def fetch_url(url: str, timeout: int = 20) -> str | None:
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = data.decode("latin-1")
                return text
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"    ✗ {e}")
                return None


def clean_gutenberg(text: str) -> str:
    start = text.find("*** START OF THE")
    if start == -1:
        start = text.find("***START OF THE")
    if start == -1:
        start = 0
    end = text.find("*** END OF THE")
    if end == -1:
        end = text.find("***END OF THE")
    if end == -1:
        end = len(text)
    content = text[start:end] if start > 0 else text[:end]
    lines = []
    for line in content.split('\n'):
        stripped = line.strip()
        if (stripped.startswith("***") or
                stripped.startswith("Project Gutenberg") or
                stripped.startswith("End of the Project Gutenberg")):
            continue
        lines.append(line)
    content = '\n'.join(lines)
    content = re.sub(r'\n{4,}', '\n\n\n', content)
    return content.strip()


def chunk_text(text: str, max_chars: int = 600) -> list[str]:
    chunks = []
    paragraphs = text.split('\n')
    current = []
    current_len = 0
    for para in paragraphs:
        para = para.strip()
        if not para:
            if current:
                chunks.append(' '.join(current))
                current = []
                current_len = 0
            continue
        para_len = len(para)
        if current_len + para_len > max_chars and current:
            chunks.append(' '.join(current))
            current = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len
    if current:
        chunks.append(' '.join(current))
    return chunks


def load_existing() -> list[str]:
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            return [l.strip() for l in f if l.strip()]
    return []


def save_lines(lines: list[str], mode: str = 'w'):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, mode, encoding='utf-8') as f:
        for line in lines:
            f.write(line + '\n')


def report(lines: list[str], label: str):
    chars = sum(len(l) for l in lines)
    print(f"  → {len(lines):,} lines | {chars:,} chars (~{chars // 4:,} est. tokens)")


def main():
    print("=" * 60)
    print("GENERATING DABBA TRAINING DATA")
    print("=" * 60)

    all_lines: list[str] = []
    total_new = 0

    # --- Phase 1: Knowledge base Q&A with question variants ---
    print(f"\n--- Phase 1: Knowledge base ({len(KNOWLEDGE_BASE)} topics × "
          f"{len(QUESTION_TEMPLATES)} question variants) ---")
    qa_lines = generate_qa_lines(KNOWLEDGE_BASE, QUESTION_TEMPLATES)
    report(qa_lines, "knowledge Q&A")
    save_lines(qa_lines, 'w')
    all_lines.extend(qa_lines)
    total_new += len(qa_lines)

    # --- Phase 2: Out-of-scope graceful decline examples ---
    print(f"\n--- Phase 2: Out-of-scope examples ({len(OUT_OF_SCOPE_PAIRS)} pairs) ---")
    oos_lines = generate_out_of_scope_lines(OUT_OF_SCOPE_PAIRS)
    report(oos_lines, "out-of-scope")
    save_lines(oos_lines, 'a')
    all_lines.extend(oos_lines)
    total_new += len(oos_lines)

    # --- Phase 3: Conversation examples ---
    print(f"\n--- Phase 3: Conversation examples ({len(CONVERSATION_EXAMPLES)} conversations) ---")
    conv_lines = generate_conversation_lines(CONVERSATION_EXAMPLES)
    report(conv_lines, "conversations")
    save_lines(conv_lines, 'a')
    all_lines.extend(conv_lines)
    total_new += len(conv_lines)

    # --- Phase 4: Gutenberg books ---
    print(f"\n--- Phase 4: Gutenberg Books ({len(GUTENBERG_SOURCES)} books) ---")
    for idx, (url, title) in enumerate(GUTENBERG_SOURCES):
        print(f"  [{idx + 1}/{len(GUTENBERG_SOURCES)}] {title}... ", end="", flush=True)
        text = fetch_url(url, timeout=30)
        if text and len(text) > 5000:
            clean = clean_gutenberg(text)
            chunks = chunk_text(clean, max_chars=800)
            chunks = [c for c in chunks if len(c) > 100]
            save_lines(chunks, 'a')
            all_lines.extend(chunks)
            total_new += len(chunks)
            print(f"✓ {len(chunks)} chunks, {len(clean):,} chars")
        else:
            print("✗ failed")
        time.sleep(1.5)

    # Stats
    total_chars = sum(len(l) for l in all_lines)
    est_tokens = total_chars // 4
    print(f"\n{'=' * 60}")
    print(f"FINAL DATASET")
    print(f"{'=' * 60}")
    print(f"  Topics:         {len(KNOWLEDGE_BASE):,}")
    print(f"  Q variants/topic: {len(QUESTION_TEMPLATES)}")
    print(f"  Lines total:    {len(all_lines):,}")
    print(f"  New added:      {total_new:,}")
    print(f"  Total chars:    {total_chars:,}")
    print(f"  Est. tokens:    ~{est_tokens:,}")
    print(f"  Size on disk:   {total_chars / 1024 / 1024:.1f} MB")
    print(f"  Output:         {OUTPUT_FILE}")

    with open(LOG_FILE, 'w') as f:
        json.dump({
            "total_lines": len(all_lines),
            "total_chars": total_chars,
            "est_tokens": est_tokens,
            "sources": {
                "knowledge_base_topics": len(KNOWLEDGE_BASE),
                "question_variants_per_topic": len(QUESTION_TEMPLATES),
                "out_of_scope_pairs": len(OUT_OF_SCOPE_PAIRS),
                "conversation_examples": len(CONVERSATION_EXAMPLES),
                "gutenberg_books": len(GUTENBERG_SOURCES),
            }
        }, f, indent=2)

    print(f"\nDone! Next: python3 train_dabba.py")


if __name__ == "__main__":
    main()
