# PC Analysis & D: Drive Migration Plan

**Date:** 2026-03-11  
**Purpose:** Ensure all work survives future C: drive formats. Move everything to D: drive.

---

## 📊 Current System Analysis

### ✅ Already on D: Drive (Safe)
| Location | Contents | Status |
|----------|----------|--------|
| `D:\openclaw\` | OpenClaw workspace, all CHIMERA projects | ✅ **SAFE** |
| `D:\appforge-main\` | AppForge repo + 8 cloned repos (langgraph, crewAI, etc.) | ✅ **SAFE** |
| `D:\picoclaw\` | PicoClaw project | ✅ **SAFE** |

### ⚠️ On C: Drive (At Risk)
| Location | Contents | Action Needed |
|----------|----------|---------------|
| `C:\Program Files\nodejs\` | Node.js 24.14.0, npm | **Reinstall to D:** |
| `C:\Program Files\Python314\` | Python 3.14.3 | **Reinstall to D:** |
| `C:\Program Files\Git\` | Git 2.53.0 | **Reinstall to D:** |
| `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.1\` | CUDA Toolkit 13.1 | **Reinstall to D:** |
| `C:\Users\garza\AppData\Roaming\npm\node_modules\` | OpenClaw, clawhub (global npm packages) | **Move/Reinstall** |
| `C:\Users\garza\.openclaw\` | OpenClaw config (openclaw.json) | **Backup + Restore** |
| `C:\Users\garza\AppData\Local\` | Various app caches, WSL | **Review** |

---

## 🔧 Programs to Reinstall on D: Drive

### 1. Node.js (Priority: HIGH)
**Current:** `C:\Program Files\nodejs\`  
**Action:** Reinstall with custom path `D:\Program Files\nodejs\`

```powershell
# Download installer
# Run with custom path: D:\Program Files\nodejs\
# After install, update PATH manually if needed
```

**Post-install:**
```powershell
# Reinstall global packages
npm install -g openclaw clawhub
```

### 2. Python 3.14 (Priority: HIGH)
**Current:** `C:\Program Files\Python314\`  
**Action:** Reinstall with custom path `D:\Program Files\Python314\`

```powershell
# Download Python 3.14 installer
# Run with custom path: D:\Program Files\Python314\
# Check "Add to PATH" option
```

**Post-install:**
```powershell
# Reinstall critical packages
pip install llama-cpp-python torch numpy pandas requests fastapi uvicorn
pip install langchain langgraph crewai autogen
pip install qiskit qdrant-client
```

### 3. Git (Priority: MEDIUM)
**Current:** `C:\Program Files\Git\`  
**Action:** Reinstall to `D:\Program Files\Git\`

```powershell
# Download Git for Windows
# Custom install path: D:\Program Files\Git\
```

### 4. CUDA Toolkit 13.1 (Priority: HIGH - for GPU acceleration)
**Current:** `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.1\`  
**Action:** Reinstall to `D:\NVIDIA\CUDA\v13.1\`

```powershell
# Download CUDA 13.1 from NVIDIA
# Custom install: D:\NVIDIA\CUDA\v13.1\
# This is CRITICAL for llama.cpp GPU acceleration
```

### 5. VS Code (Priority: LOW - can stay on C:)
**Current:** `C:\Program Files\Microsoft VS Code\`  
**Action:** Optional - can stay on C: (small footprint)

---

## 📁 Files to Backup from C: Drive

### Critical Configs
```powershell
# Backup these BEFORE any uninstall:
Copy-Item C:\Users\garza\.openclaw\openclaw.json D:\openclaw\backup\
Copy-Item C:\Users\garza\.openclaw\openclaw.env D:\openclaw\backup\ 2>$null

# Backup npm global packages list
npm list -g --depth=0 > D:\openclaw\backup\npm-globals.txt

# Backup pip packages
pip list > D:\openclaw\backup\pip-packages.txt
```

### Environment Variables
Check and document:
- `PATH` additions
- `PYTHONPATH`
- `CUDA_PATH`
- `NODE_PATH`

---

## 🚀 Migration Steps

### Phase 1: Backup (DO THIS FIRST)
```powershell
# Create backup directory
New-Item -ItemType Directory -Force D:\openclaw\backup\

# Backup OpenClaw config
Copy-Item C:\Users\garza\.openclaw\ D:\openclaw\backup\openclaw-config\ -Recurse

# Export package lists
npm list -g --depth=0 > D:\openclaw\backup\npm-globals.txt
pip freeze > D:\openclaw\backup\pip-requirements.txt

# Document environment variables
Get-ChildItem Env: | Out-File D:\openclaw\backup\environment-variables.txt
```

### Phase 2: Uninstall C: Programs
1. Uninstall Node.js from Control Panel
2. Uninstall Python 3.14 from Control Panel
3. Uninstall Git from Control Panel
4. Uninstall CUDA Toolkit from Control Panel

### Phase 3: Reinstall to D: Drive
1. **Node.js** → `D:\Program Files\nodejs\`
2. **Python** → `D:\Program Files\Python314\`
3. **Git** → `D:\Program Files\Git\`
4. **CUDA** → `D:\NVIDIA\CUDA\v13.1\`

### Phase 4: Restore & Verify
```powershell
# Restore OpenClaw config
Copy-Item D:\openclaw\backup\openclaw-config\ C:\Users\garza\.openclaw\ -Recurse -Force

# Reinstall global npm packages
npm install -g openclaw clawhub

# Reinstall Python packages
pip install -r D:\openclaw\backup\pip-requirements.txt

# Verify installations
node --version
npm --version
python --version
git --version
nvcc --version
```

### Phase 5: Update PATH (if needed)
Add to System PATH:
- `D:\Program Files\nodejs\`
- `D:\Program Files\Python314\`
- `D:\Program Files\Python314\Scripts\`
- `D:\Program Files\Git\cmd\`
- `D:\NVIDIA\CUDA\v13.1\bin\`
- `D:\NVIDIA\CUDA\v13.1\libnvvp\`

---

## 📋 Recommended D: Drive Structure

```
D:\
├── Program Files\          # All installed programs
│   ├── nodejs\
│   ├── Python314\
│   ├── Git\
│   └── Microsoft VS Code\  (optional)
│
├── NVIDIA\                 # NVIDIA tools
│   └── CUDA\v13.1\
│
├── openclaw\              # OpenClaw workspace (EXISTING)
│   ├── memory\
│   ├── CHIMERA projects\
│   └── backup\            # Config backups
│
├── appforge-main\         # AppForge repo (EXISTING)
├── picoclaw\              # PicoClaw (EXISTING)
│
└── Projects\              # Future projects
    └── [new projects]
```

---

## ⚡ Quick Start Script (After Reinstall)

Save as `D:\openclaw\scripts\restore-environment.ps1`:

```powershell
# Restore OpenClaw config
Copy-Item D:\openclaw\backup\openclaw-config\ $env:USERPROFILE\.openclaw\ -Recurse -Force

# Verify Node.js
if (Test-Path "D:\Program Files\nodejs\node.exe") {
    Write-Host "✅ Node.js OK"
    & "D:\Program Files\nodejs\npm.exe" install -g openclaw clawhub
}

# Verify Python
if (Test-Path "D:\Program Files\Python314\python.exe") {
    Write-Host "✅ Python OK"
    & "D:\Program Files\Python314\python.exe" -m pip install -r D:\openclaw\backup\pip-requirements.txt
}

# Verify CUDA
if (Test-Path "D:\NVIDIA\CUDA\v13.1\bin\nvcc.exe") {
    Write-Host "✅ CUDA OK"
}

Write-Host "🎉 Environment restored!"
```

---

## 🔍 Current Installed Programs Summary

| Program | Version | Location | Priority |
|---------|---------|----------|----------|
| Node.js | 24.14.0 | C: | 🔴 Reinstall to D: |
| Python | 3.14.3 | C: | 🔴 Reinstall to D: |
| Git | 2.53.0 | C: | 🟡 Reinstall to D: |
| CUDA | 13.1 | C: | 🔴 Reinstall to D: |
| VS Code | 1.111.0 | C: | 🟢 Can stay |
| NVIDIA App | 11.0.6.383 | C: | 🟢 Keep (drivers) |
| WSL | 2.6.3.0 | System | 🟢 Keep |

---

## 🎯 Next Actions

1. **IMMEDIATE:** Run backup script to save configs
2. **Download installers** for Node.js, Python, Git, CUDA
3. **Uninstall** C: versions
4. **Reinstall** to D: with custom paths
5. **Restore** configs and packages
6. **Test** CHIMERA servers and OpenClaw

---

**Status:** Analysis complete. Ready to execute migration plan.
