# DABBA — Complete AI Platform Architecture

## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
##                        VISION
## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Build a production-grade open-source AI assistant platform (Claude-like) with:
- Custom decoder-only transformer trained from scratch
- RAG pipeline for document knowledge
- MCP (Model Context Protocol) for tool/function calling
- Multimodal support (images, video, audio)
- Terminal CLI agent (like Claude Code)
- VS Code extension
- Chrome extension
- Modern chat UI (React)

## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#                     COMPLETE ARCHITECTURE
## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
                                   USER INTERFACES
                ┌───────────────────────────────────────────────┐
                │  Terminal CLI   │  VS Code Ext  │  Chrome Ext │
                │  (Session Agent)│  (Side Panel) │  (Sidebar)  │
                └────────┬───────┴───────┬───────┴──────┬──────┘
                         │               │              │
                         ▼               ▼              ▼
                ┌───────────────────────────────────────────────┐
                │              FastAPI Server                   │
                │  (OpenAI-compatible / Streaming / Auth / RL)  │
                └────────┬──────────────────────────────────────┘
                         │
                         ▼
                ┌───────────────────────────────────────────────┐
                │            AGENT ORCHESTRATOR                  │
                │  ┌─────────┐  ┌──────────┐  ┌─────────────┐  │
                │  │ Planner │  │ Executor │  │ Memory Mgr  │  │
                │  └─────────┘  └──────────┘  └─────────────┘  │
                │  ┌─────────┐  ┌──────────┐  ┌─────────────┐  │
                │  │ MCP     │  │ Tool     │  │ Context     │  │
                │  │ Handler │  │ Registry │  │ Manager     │  │
                │  └─────────┘  └──────────┘  └─────────────┘  │
                └───────────────────────────────────────────────┘
                         │
            ┌────────────┼────────────────┬───────────────────┐
            ▼            ▼                ▼                   ▼
    ┌────────────┐ ┌──────────┐ ┌──────────────┐ ┌────────────────┐
    │  LLM       │ │  RAG     │ │  Multimodal  │ │  Memory Store  │
    │  Engine    │ │  Pipeline│ │  Encoder     │ │  (Vector DB)   │
    │  (dabba)   │ │          │ │  (Vision)    │ │                │
    └────────────┘ └──────────┘ └──────────────┘ └────────────────┘
```

## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#                 SESSION BREAKDOWN (11 Sessions)
## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### SESSION 1 — Core Training Framework (dabba core)
═══════════════════════════════════════════════════════

FILES: ~25 files, ~4000 lines
ESTIMATE: One extended session

dabba/
├── __init__.py
├── config/
│   ├── __init__.py
│   ├── model_config.py          # Model hyperparameters dataclass
│   ├── training_config.py       # Training hyperparameters
│   └── data_config.py           # Data pipeline config
├── tokenizer/
│   ├── __init__.py
│   ├── bpe_tokenizer.py         # BPE from scratch
│   ├── vocab_trainer.py         # Vocabulary training
│   └── special_tokens.py        # Special tokens enum
├── data/
│   ├── __init__.py
│   ├── text_cleaner.py          # Text cleaning pipeline
│   ├── deduplication.py         # MinHash dedup
│   ├── document_parser.py       # Parse various formats
│   ├── chunker.py               # Document chunking
│   ├── streaming_dataset.py     # Memory-mapped streaming
│   ├── packer.py                # Packed sequences
│   └── dataloader.py            # Custom DataLoader
├── model/
│   ├── __init__.py
│   ├── embedding.py             # TokenEmbedding + RoPE
│   ├── normalizations.py        # RMSNorm, LayerNorm
│   ├── attention.py             # MHA, GQA, MQA, FlashAttn wrapper
│   ├── feed_forward.py          # SwiGLU, GELU, FFN
│   ├── decoder_block.py         # Single decoder block
│   ├── transformer.py           # Full transformer stack
│   ├── kv_cache.py              # KV cache for inference
│   └── output_head.py           # LM head + weight tying
├── trainer/
│   ├── __init__.py
│   ├── optimizer.py             # AdamW from scratch
│   ├── lr_scheduler.py          # Cosine/warmup scheduler
│   ├── train_step.py            # Single training step
│   ├── checkpoint.py            # Save/resume checkpoints
│   ├── validator.py             # Validation loop
│   └── metrics.py               # Perplexity, accuracy, loss
├── inference/
│   ├── __init__.py
│   ├── generator.py             # Token generation
│   ├── samplers.py              # Top-K, Top-P, temperature
│   ├── beam_search.py           # Beam search decoder
│   └── streaming.py             # Streaming output
├── scripts/
│   ├── train.py                 # Main training script
│   └── generate.py              # Generation script
└── utils/
    ├── __init__.py
    ├── logging.py               # Logging utilities
    ├── config_loader.py          # YAML config loader
    └── distributed.py            # DDP utilities

DELIVERABLES:
  ✅ Load any model config from YAML (10M → 7B)
  ✅ Train BPE tokenizer on custom data
  ✅ Streaming dataloader with packed sequences
  ✅ Full decoder transformer (RoPE, RMSNorm, GQA, SwiGLU)
  ✅ Training loop (AdamW, AMP, gradient clipping, checkpoint)
  ✅ Text generation (top-k, top-p, temperature, beam search)
  ✅ TensorBoard logging + loss graphs
  ✅ Train a 10M param model end-to-end as proof

---

### SESSION 2 — RAG Pipeline
═══════════════════════════════════════════════════════

FILES: ~12 files, ~2000 lines
ESTIMATE: One extended session

dabba/
├── rag/
│   ├── __init__.py
│   ├── embedding_model.py       # Text embedding (sentence-transformers wrapper)
│   ├── vector_store.py          # Vector DB interface (Chroma/Pinecone)
│   ├── document_indexer.py      # Index documents
│   ├── retriever.py             # Document retrieval
│   ├── reranker.py              # Cross-encoder re-ranking
│   ├── hybrid_search.py         # Dense + sparse (BM25) hybrid
│   └── rag_pipeline.py          # Full RAG pipeline
└── config/
    └── rag_config.py            # RAG configuration

DELIVERABLES:
  ✅ Embed documents (PDF, text, markdown)
  ✅ Store in vector database
  ✅ Retrieve top-K relevant documents
  ✅ Re-rank with cross-encoder
  ✅ Hybrid search (dense + sparse)
  ✅ Full RAG pipeline (query → retrieve → rerank → respond)

---

### SESSION 3 — MCP + Agent Loop + Function Calling
═══════════════════════════════════════════════════════

FILES: ~12 files, ~2000 lines
ESTIMATE: One extended session

dabba/
├── agent/
│   ├── __init__.py
│   ├── mcp_handler.py           # Model Context Protocol
│   ├── tool_registry.py         # Tool registration & dispatch
│   ├── tool_schema.py           # Tool definition schema
│   ├── planner.py               # Multi-step planning
│   ├── executor.py              # Execute planned steps
│   ├── context_manager.py       # Context window management
│   └── agent_loop.py            # Main agent orchestration loop
├── tools/
│   ├── __init__.py
│   ├── file_tools.py            # Read/write/search files
│   ├── shell_tools.py           # Execute commands
│   ├── web_tools.py             # Web fetch/search
│   ├── code_tools.py            # Code analysis & editing
│   └── rag_tool.py              # RAG query tool
└── config/
    └── agent_config.py          # Agent configuration

DELIVERABLES:
  ✅ MCP message format (structured tool calls)
  ✅ Tool registry with schema validation
  ✅ File operations (read, write, edit, grep)
  ✅ Shell command execution
  ✅ Web fetching + search
  ✅ Multi-step planning & execution
  ✅ Context window management

---

### SESSION 4 — Multimodal (Vision + Audio + Video)
═══════════════════════════════════════════════════════

FILES: ~10 files, ~2000 lines
ESTIMATE: One extended session

dabba/
├── multimodal/
│   ├── __init__.py
│   ├── vision_encoder.py        # Image encoder (SigLIP/ViT wrapper)
│   ├── image_processor.py       # Image preprocessing
│   ├── video_processor.py       # Video frame extraction
│   ├── audio_processor.py       # Audio transcription (Whisper)
│   ├── multimodal_projection.py # Project vision→LLM embedding space
│   ├── multimodal_attention.py  # Cross-attention for vision tokens
│   └── multimodal_llm.py        # Full multimodal language model
└── config/
    └── multimodal_config.py     # Multimodal config

DELIVERABLES:
  ✅ Image input → encode → project → LLM
  ✅ Video frame sampling + processing
  ✅ Audio transcription → text input
  ✅ File upload handling (images, PDFs, video)
  ✅ Vision-language understanding

---

### SESSION 5 — FastAPI Server
═══════════════════════════════════════════════════════

FILES: ~10 files, ~1500 lines
ESTIMATE: One extended session

dabba/
├── api/
│   ├── __init__.py
│   ├── server.py                # FastAPI application
│   ├── chat_endpoints.py        # Chat completions endpoint
│   ├── embedding_endpoints.py   # Embeddings endpoint
│   ├── model_endpoints.py       # Model listing
│   ├── streaming_handler.py     # SSE streaming
│   ├── auth.py                  # API key authentication
│   ├── rate_limiter.py          # Rate limiting
│   └── openai_compat.py         # OpenAI-compatible schema
└── config/
    └── api_config.py            # Server config

DELIVERABLES:
  ✅ POST /v1/chat/completions (streaming + non-streaming)
  ✅ POST /v1/embeddings
  ✅ GET  /v1/models
  ✅ OpenAI-compatible request/response format
  ✅ API key authentication
  ✅ Rate limiting (per-key, per-IP)
  ✅ SSE streaming responses
  ✅ Docker deployment

---

### SESSION 6 — Terminal CLI Agent (Claude Code Clone)
═══════════════════════════════════════════════════════

FILES: ~8 files, ~1500 lines
ESTIMATE: One extended session

dabba/
├── cli/
│   ├── __init__.py
│   ├── main.py                  # CLI entry point
│   ├── session.py               # Interactive session loop
│   ├── agent_proxy.py           # Agent orchestration
│   ├── output_handler.py        # Rich terminal output
│   ├── file_watcher.py          # Watch file changes
│   └── permissions.py           # Permission system (approve shell cmds)
└── scripts/
    └── dabba-cli                # Shell entry point

DELIVERABLES:
  ✅ Interactive terminal session
  ✅ File editing with diff display
  ✅ Shell command execution with approval
  ✅ Rich output (syntax highlighting, markdown)
  ✅ Permission system (allow/deny/ask)
  ✅ Session persistence
  ✅ Exit summary

---

### SESSION 7 — Chat UI (React Frontend)
═══════════════════════════════════════════════════════

FILES: ~20 files, ~3000 lines
ESTIMATE: One extended session

frontend/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── components/
│   │   ├── ChatWindow.tsx       # Main chat view
│   │   ├── MessageBubble.tsx    # Individual message
│   │   ├── InputArea.tsx        # Message input
│   │   ├── Sidebar.tsx          # Chat history
│   │   ├── MarkdownRenderer.tsx # Markdown + code highlighting
│   │   ├── FileUpload.tsx       # File/image upload
│   │   ├── ImagePreview.tsx     # Image preview in chat
│   │   └── ConversationList.tsx # Saved conversations
│   ├── hooks/
│   │   ├── useChat.ts           # Chat state management
│   │   ├── useStreaming.ts      # SSE stream handling
│   │   └── useHistory.ts        # Conversation history
│   ├── api/
│   │   └── client.ts            # API client
│   └── styles/
│       └── globals.css

DELIVERABLES:
  ✅ Modern chat interface (dark/light mode)
  ✅ Markdown rendering + code syntax highlighting
  ✅ Streaming response display
  ✅ File upload (images, PDF, text)
  ✅ Image preview in chat
  ✅ Conversation history sidebar
  ✅ Export conversations
  ✅ Responsive design

---

### SESSION 8 — VS Code Extension
═══════════════════════════════════════════════════════

FILES: ~12 files, ~2000 lines
ESTIMATE: Two sessions (complexity)

vscode-extension/
├── package.json
├── tsconfig.json
├── .vscodeignore
├── src/
│   ├── extension.ts             # Extension entry point
│   ├── sidePanel.ts             # Side panel webview
│   ├── chatViewProvider.ts      # Webview provider
│   ├── inlineChat.ts            # Inline chat (cmd+I)
│   ├── codeActions.ts           # Code actions provider
│   ├── diagnostics.ts           # Problem matcher
│   ├── commands.ts              # Command registration
│   └── settings.ts              # Extension settings
├── media/
│   ├── main.js                  # Webview JS
│   └── style.css                # Webview styles
└── test/
    └── extension.test.ts

DELIVERABLES:
  ✅ Side panel chat (open in sidebar)
  ✅ Inline code chat (select text → ask)
  ✅ Code insertion/editing from chat
  ✅ File context awareness
  ✅ Syntax highlighting in responses
  ✅ Settings configuration
  ✅ VS Code marketplace packaging

---

### SESSION 9 — Chrome Extension
═══════════════════════════════════════════════════════

FILES: ~8 files, ~1000 lines
ESTIMATE: One session

chrome-extension/
├── manifest.json
├── background.js                # Background service worker
├── content.js                   # Page content script
├── popup/
│   ├── popup.html               # Popup UI
│   ├── popup.js                 # Popup logic
│   └── popup.css
├── sidebar/
│   ├── sidebar.html             # Sidebar panel
│   ├── sidebar.js               # Sidebar logic
│   └── sidebar.css
├── options/
│   ├── options.html             # Settings page
│   └── options.js
└── icons/

DELIVERABLES:
  ✅ Sidebar chat (open on any page)
  ✅ Page content extraction (send to AI)
  ✅ Text selection → ask AI
  ✅ Popup quick chat
  ✅ API key configuration
  ✅ Chrome Web Store packaging

---

### SESSION 10 — Evaluation + Benchmarking + Optimization
═══════════════════════════════════════════════════════

FILES: ~8 files, ~1500 lines
ESTIMATE: One session

dabba/
├── evaluation/
│   ├── __init__.py
│   ├── perplexity.py            # Perplexity evaluation
│   ├── benchmark.py             # Performance benchmarks
│   ├── latency.py               # Latency measurements
│   ├── memory_profile.py        # Memory usage profiling
│   └── benchmark_suite.py       # Full benchmark runner
├── optimization/
│   ├── __init__.py
│   ├── gradient_checkpointing.py # Checkpointing wrapper
│   ├── activation_recomputation.py
│   ├── kv_cache_opt.py          # PagedAttention-style cache
│   └── quantization.py          # INT8/FP4 quantization
└── scripts/
    └── benchmark.py              # Run benchmarks

DELIVERABLES:
  ✅ Perplexity on validation set
  ✅ Tokens/second throughput
  ✅ Memory usage breakdown
  ✅ GPU utilization metrics
  ✅ Latency benchmarks (TTFT, TPOT)
  ✅ Optimization strategies applied
  ✅ Benchmark report generation

---

### SESSION 11 — Testing + Documentation + Dockerization
═══════════════════════════════════════════════════════

FILES: ~15 files, ~2000 lines
ESTIMATE: One session

dabba/
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_tokenizer.py
│   ├── test_data.py
│   ├── test_model.py
│   ├── test_attention.py
│   ├── test_trainer.py
│   ├── test_inference.py
│   ├── test_rag.py
│   ├── test_agent.py
│   ├── test_api.py
│   └── test_multimodal.py
├── docs/
│   ├── index.md
│   ├── installation.md
│   ├── configuration.md
│   ├── training.md
│   ├── rag.md
│   ├── inference.md
│   ├── api.md
│   └── deployment.md
├── Dockerfile
├── docker-compose.yml
└── scripts/
    ├── test.sh                   # Run all tests
    └── deploy.sh                 # Deployment script

DELIVERABLES:
  ✅ All unit tests pass
  ✅ Integration tests
  ✅ GPU tests (if GPU available)
  ✅ Comprehensive documentation
  ✅ Docker containerization
  ✅ CI/CD configuration

---

## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#                 TIMELINE SUMMARY
## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Per Session: I deliver whatever is in the session plan.
### You don't wait days — you get the code immediately.

Session  │ Component                          │ Files  │ Lines
─────────┼────────────────────────────────────┼───────┼────────
  1      │ dabba core (config, tokenizer,     │  25   │ ~4000
         │ data, model, trainer, inference)    │       │
  2      │ RAG pipeline                       │  12   │ ~2000
  3      │ MCP + Agent + Function Calling     │  12   │ ~2000
  4      │ Multimodal (vision, audio, video)  │  10   │ ~2000
  5      │ FastAPI server                     │  10   │ ~1500
  6      │ Terminal CLI agent                 │   8   │ ~1500
  7      │ Chat UI (React)                    │  20   │ ~3000
  8      │ VS Code extension                  │  12   │ ~2000
  9      │ Chrome extension                   │   8   │ ~1000
 10      │ Evaluation + Optimization          │   8   │ ~1500
 11      │ Testing + Documentation + Docker   │  15   │ ~2000
─────────┼────────────────────────────────────┼───────┼────────
 TOTAL   │ Complete AI Platform               │  140  │ ~23,500

### ENGINEERING TIME
─────────────────────────────────────────────────────────
Building everything:  11 sessions (in this chat)
Your time:            Just reading + reviewing + testing
My time:              As long as you keep the chat open

### WHAT YOU NEED ON YOUR END
─────────────────────────────────────────────────────────
Component           │ Requirement
────────────────────┼───────────────────────────────────
dabba training      │ GPU (RTX 3090+ recommended)
Running LLM         │ GPU + 8GB+ VRAM (for 1B model)
RAG                 │ CPU + 16GB RAM is sufficient
Agent/CLI           │ Any machine
Chat UI             │ Any machine
VS Code ext         │ VS Code with Node.js
Chrome ext          │ Chrome/Chromium browser
Server deployment   │ Linux VPS or cloud VM with GPU

### MODEL OPTIONS (IF YOU DON'T TRAIN YOUR OWN)
─────────────────────────────────────────────────────────
You can plug in any of these instead — the platform works
the same either way:

Model              │ Size    │ VRAM     │ Quality
───────────────────┼─────────┼──────────┼──────────────
Llama 3.2          │ 1B      │ 2-4 GB   │ Decent
Llama 3.2          │ 3B      │ 6-8 GB   │ Good
Qwen 2.5           │ 7B      │ 14-16 GB │ Very good
DeepSeek Coder     │ 6.7B    │ 12-14 GB │ Excellent code
Mixtral 8x7B       │ 46B(MoE)│ 24-32 GB │ Excellent
Llama 3            │ 8B      │ 16 GB    │ Excellent
─────────────────────────────────────────────────────────
All runnable via Ollama, vLLM, or llama.cpp

---

## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#              ARCHITECTURE DECISIONS
## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Why build from scratch instead of using HF Transformers?
• Complete control over every weight and computation
• Deep understanding of transformer internals
• No black boxes — you see every layer's code
• Educational value for training your own models
• Easy to modify any component (custom attention, etc.)

### Why PyTorch instead of JAX?
• Broader ecosystem
• Easier debugging
• More community tools
• Better for single-GPU training
• CUDA kernel support

### Why pluggable models?
• Train your own when you have GPU time
• Use open-source models for production
• Hot-swap between custom and pre-trained
• Compare performance across model families

### Security model
• API key authentication
• Rate limiting per key/IP
• File upload validation (type, size, content)
• Command execution requires approval (CLI agent)
• Sandboxed code execution

---

## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#             HOW EACH SESSION WORKS
## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. You say "Start Session X"
2. I write every file for that session in one go
3. You can test, review, or ask for changes
4. When satisfied, we move to next session
5. Sessions build on each other (Session 6 needs Session 1+3+5)

### Testing as we go
• Each session's code is self-contained
• I provide test commands per session
• You verify before moving to next session

---

## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#                    NEXT STEPS
## ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

To start: say "Start Session 1"

I'll build the entire dabba core — all 25 files — in one shot:
• Config system (YAML-driven)
• BPE tokenizer (train from scratch)
• Data pipeline (streaming, packed, shuffled)
• Full decoder-only transformer (RoPE, RMSNorm, GQA, SwiGLU)
• Training engine (AdamW, AMP, checkpointing, TensorBoard)
• Inference (sampling, beam search, streaming)
• Training script (train a 10M model on your data)

Everything is production code — no TODOs, no placeholders,
every function documented, every module tested.
