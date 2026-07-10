#!/bin/bash
# Start Dabba AI - Backend and Frontend

echo "🚀 Starting Dabba AI System..."
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Start Backend
echo -e "${BLUE}▶ Starting Backend (port 8080)...${NC}"
python3 -m dabba.api.server > dabba_logs/dabba-backend.log 2>&1 &
BACKEND_PID=$!
echo -e "${GREEN}✓ Backend started (PID: $BACKEND_PID)${NC}"

sleep 3

# Start Frontend
echo ""
echo -e "${BLUE}▶ Starting Frontend (port 5173)...${NC}"
cd frontend
npm run dev > ../dabba_logs/dabba-frontend.log 2>&1 &
FRONTEND_PID=$!
echo -e "${GREEN}✓ Frontend started (PID: $FRONTEND_PID)${NC}"

echo ""
echo "="*60
echo -e "${GREEN}✨ Dabba AI is running!${NC}"
echo "="*60
echo ""
echo "Backend:  http://localhost:8080"
echo "Frontend: http://localhost:5173"
echo ""
echo "Backend logs:  tail -f dabba_logs/dabba-backend.log"
echo "Frontend logs: tail -f dabba_logs/dabba-frontend.log"
echo ""
echo "To stop: kill $BACKEND_PID $FRONTEND_PID"
echo ""

# Wait for both processes
wait
