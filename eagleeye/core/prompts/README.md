# EagleEye System Prompts

All system prompts are stored as **YAML files** for easy customization and versioning.

## Structure

```
eagleeye/core/prompts/
├── README.md                    ← You are here
├── parameters.yml               ← Global parameters (shared by all prompts)
├── synthesis.yml               ← Multi-agent findings synthesizer
├── agents/
│   ├── pr.yml                 ← Code logic & correctness
│   ├── schema.yml             ← DDL & schema changes
│   ├── lineage.yml            ← Pipeline dependencies & CI/CD
│   ├── reference.yml          ← Cross-repo impact
│   └── arch_drift.yml         ← Architectural layer violations
└── utils/
    ├── repo_reader.yml        ← Repo onboarding documentation
    ├── bug_scanner.yml        ← Security & correctness audit
    └── diagram.yml            ← Architecture diagram generation
```

## How Prompts are Loaded

1. **Parameters** (`parameters.yml`) are loaded first
2. **Each prompt YAML file** contains a `system_prompt` field with `{{PARAM}}` placeholders
3. At runtime, **parameters are substituted** into prompts (e.g., `{{max_file_comments}}` → `8`)

## Customizing Prompts

### Option A: Edit in Source Code (Versioned)

Edit any YAML file here in the repo. Changes are tracked in git and shared with all users.

```bash
# Edit the PR agent prompt
vim eagleeye/core/prompts/agents/pr.yml

# Change severity definitions globally
vim eagleeye/core/prompts/parameters.yml

# Commit and push
git add eagleeye/core/prompts/
git commit -m "refine: tighten critical severity threshold"
git push
```

### Option B: Override Locally (User-Specific)

Copy prompts to `~/.eagleeye/core/prompts/` for personal overrides (does NOT check into git).

```bash
# Create user override directory
mkdir -p ~/.eagleeye/core/prompts/agents ~/.eagleeye/core/prompts/utils

# Copy and customize
cp -r eagleeye/core/prompts/* ~/.eagleeye/core/prompts/
vim ~/.eagleeye/core/prompts/parameters.yml

# Now your custom prompts are used locally
eagleeye review owner/repo 42
```

The loader uses this priority:
1. **User override:** `~/.eagleeye/core/prompts/` (if exists)
2. **Source code:** `eagleeye/core/prompts/` (default)

## Parameters Guide

Edit `parameters.yml` to tune global behavior:

| Parameter | Purpose | Default | Example |
|-----------|---------|---------|---------|
| `max_file_comments` | Max findings in final report | `8` | Change to `5` for stricter limit |
| `max_findings_per_agent` | Max findings per agent | `8` | Change to `10` for more detail |
| `severity_critical` | Definition of "critical" | (see below) | Customize the standard |
| `severity_high` | Definition of "high" | (see below) | Customize the standard |
| `severity_medium` | Definition of "medium" | (see below) | Customize the standard |
| `severity_low` | Definition of "low" | (see below) | Customize the standard |
| `critical_threshold` | # critical findings → critical risk | `2` | Change to `1` for stricter |
| `high_threshold` | # high findings → high risk | `1` | Change to `2` for lenient |

## Default Severity Definitions

**Critical:** Code that WILL break at runtime under normal usage — confirmed exceptions, data loss, or exploitable security vulnerability

**High:** Bug that WILL occur under specific but realistic and common operating conditions

**Medium:** Realistic code quality gap, missing error handling for edge cases that actually occur in production

**Low:** Only flag if it would actively mislead future developers, mask a real bug, or cause maintenance problems

## Customization Examples

### Example 1: Make Critical Threshold Stricter

**Before:** 2+ critical findings needed for "critical" risk level

**Edit:** `parameters.yml`
```yaml
critical_threshold: 1  # Now only 1 critical finding = critical risk
```

**Result:** More aggressive risk reporting

---

### Example 2: Lenient on Non-Breaking Issues

**Before:** High severity required for "comment" verdict

**Edit:** `eagleeye/core/prompts/synthesis.yml`

Find the verdict section and change:
```
request_changes: a critical finding is present that WILL break production
comment: high findings worth addressing, but nothing production-breaking
```

To:
```
request_changes: 2+ critical findings that WILL break production
comment: 1+ critical finding OR any high findings worth addressing
```

---

### Example 3: Tighten Security Standards

**Before:** Generic OWASP top 10 list

**Edit:** `eagleeye/core/prompts/utils/bug_scanner.yml`

Add language-specific footguns relevant to your stack:

```yaml
system_prompt: |
  You have expertise in:
  - OWASP Top 10 security vulnerabilities (injection, broken auth, XSS, IDOR, SSRF, etc.)
  - Your-specific stack concerns:
    Snowflake: improper role grants, secrets in comment fields, unencrypted PII columns
    dbt: upstream model dependency assumptions, SQL injection via var()
    Databricks: cluster autoscaling DoS, secrets in notebook cells
```

---

### Example 4: Reduce Finding Limit for MVP

**Before:** 8 findings per report

**Edit:** `parameters.yml`
```yaml
max_file_comments: 3  # Show only top 3 most impactful findings
```

**Result:** Shorter reports, clearer priorities

---

## Available Prompts

### agents.pr
**Mode:** Multi-agent (code logic & correctness)  
**Use:** Part of 5-agent parallel review

**Scope:** Logic, performance, NEW security vulnerabilities  
**Does NOT:** Schema, pipelines, architecture

---

### agents.schema
**Mode:** Multi-agent (DDL & schema)  

**Scope:** Breaking schema changes, type mismatches, migrations  
**Does NOT:** Code logic, pipelines, architecture

---

### agents.lineage
**Mode:** Multi-agent (pipeline dependencies)  

**Scope:** Snowflake lineage, CI/CD cascades, silent failures  
**Does NOT:** Code logic, schema, architecture

---

### agents.reference
**Mode:** Multi-agent (cross-repo impact)  
**Note:** Max severity is HIGH (never critical)

**Scope:** Symbol/schema deletion impact on reference repo  
**Does NOT:** Internal code logic

---

### agents.arch_drift
**Mode:** Multi-agent (architectural integrity)  

**Scope:** Cross-layer imports, hardcoded config, circular deps  
**Does NOT:** Code logic, schema, pipelines

---

### synthesis
**Mode:** Multi-agent (deduplication & verdict)  

**Role:** Synthesizes findings from all 5 agents  
**Parameterized:**
- `{{max_file_comments}}` — max findings in final report
- `{{critical_threshold}}` — # critical → critical risk

---

### utils.repo_reader
**Use:** Onboarding documentation  
**Scope:** Architecture, tech stack, data flow, gotchas

---

### utils.bug_scanner
**Use:** Exhaustive security audit  
**Scope:** OWASP, CWE, language-specific vulnerabilities

---

### utils.diagram
**Use:** Generate Mermaid architecture diagrams  
**Scope:** Architecture visualization, change impact

---

## Testing Your Custom Prompts

```bash
# See what prompts are loaded
python3 << 'EOF'
from eagleeye.prompt_loader import load_library
lib = load_library()
print("Loaded prompts:")
for p in lib.list_prompts():
    print(f"  - {p}")
EOF

# Test parameter substitution
python3 << 'EOF'
from eagleeye.prompt_loader import load_library
lib = load_library()
prompt = lib.get_prompt("agents.pr")
if "{{" in prompt:
    print("❌ Parameters NOT substituted")
else:
    print("✅ Parameters substituted correctly")
EOF

# Generate a review with your custom prompts
eagleeye review owner/repo 42
```

---

## Version Control

✅ **Commit source prompts** (`eagleeye/core/prompts/`) to git — changes apply to whole team  
❌ **Don't commit user overrides** (`~/.eagleeye/core/prompts/`) — personal customizations only

---

## Questions?

See `PROMPTS_REFERENCE.md` for detailed documentation of each prompt's scope and severity definitions.
