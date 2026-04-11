#!/bin/bash
# Start both API and frontend with one command
echo "Starting Stock Discovery..."
echo ""

# Start API in background
echo "→ Starting API on http://localhost:8000"
cd "$(dirname "$0")"
python -m uvicorn api:app --reload --port 8000 &
API_PID=$!

# Start frontend
echo "→ Starting frontend on http://localhost:3000"
cd frontend
npm run dev &
FRONT_PID=$!

echo ""
echo "✓ API:      http://localhost:8000"
echo "✓ Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both."

trap "kill $API_PID $FRONT_PID 2>/dev/null; exit" INT TERM
wait
