#!/bin/bash
# Verification script to check project structure

echo "=========================================="
echo "Project Safezone - Structure Verification"
echo "=========================================="
echo ""

# Check backend files
echo "Checking backend structure..."
files=(
    "backend/app.py"
    "backend/init_db.py"
    "backend/requirements.txt"
    "backend/src/database.py"
    "backend/src/models/user.py"
    "backend/src/models/player.py"
    "backend/src/models/server.py"
    "backend/src/routes/auth.py"
    "backend/src/routes/players.py"
    "backend/src/routes/servers.py"
    "backend/src/routes/admin.py"
    "backend/src/middleware/auth.py"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "✓ $file"
    else
        echo "✗ $file MISSING"
    fi
done

echo ""
echo "Checking frontend structure..."
frontend_files=(
    "frontend/public/index.html"
    "frontend/src/App.js"
    "frontend/src/index.js"
    "frontend/src/components/Navbar.js"
    "frontend/src/components/Footer.js"
    "frontend/src/components/ProtectedRoute.js"
    "frontend/src/pages/Home.js"
    "frontend/src/pages/SignIn.js"
    "frontend/src/pages/Servers.js"
    "frontend/src/pages/Players.js"
    "frontend/src/pages/Profile.js"
    "frontend/src/pages/Admin.js"
    "frontend/src/context/AuthContext.js"
    "frontend/src/services/api.js"
)

for file in "${frontend_files[@]}"; do
    if [ -f "$file" ]; then
        echo "✓ $file"
    else
        echo "✗ $file MISSING"
    fi
done

echo ""
echo "Checking documentation..."
docs=(
    "README.md"
    "backend/API.md"
    "frontend/README.md"
    ".env.example"
)

for file in "${docs[@]}"; do
    if [ -f "$file" ]; then
        echo "✓ $file"
    else
        echo "✗ $file MISSING"
    fi
done

echo ""
echo "=========================================="
echo "Python syntax check..."
python3 -m py_compile backend/app.py backend/src/models/*.py backend/src/routes/*.py backend/src/middleware/*.py backend/src/database.py 2>&1
if [ $? -eq 0 ]; then
    echo "✓ All Python files have valid syntax"
else
    echo "✗ Python syntax errors found"
fi

echo ""
echo "=========================================="
echo "Verification complete!"
echo "=========================================="
