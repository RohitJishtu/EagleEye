# Day 3-4: HLD vs LLD Deep Dive

**Goal:** Understand when to use High-Level Design vs Low-Level Design  
**Time:** 2 days (4-6 hours total)

---

## 🎯 Learning Objectives

By the end of this section, you will:
- ✅ Clearly distinguish between HLD and LLD
- ✅ Know which level of design a decision belongs to
- ✅ Understand what artifacts to create for each
- ✅ Know when to escalate design decisions

---

## 📖 The Complete Comparison

### Visual Overview

```
┌─────────────────────────────────────────────────────────┐
│               System Design Spectrum                    │
└─────────────────────────────────────────────────────────┘

Business Requirements
         ↓
    [HLD Layer]  ← Architects, Managers focus here
         ↓
  Components & Modules
         ↓
    [LLD Layer]  ← Developers focus here
         ↓
  Classes & Functions
         ↓
    Implementation
```

---

## 1. Decision Classification Framework

### Rule of Thumb

Ask these questions to determine if a decision is HLD or LLD:

| Question | HLD | LLD |
|----------|-----|-----|
| **Does it affect multiple teams?** | ✅ Yes | ❌ No |
| **Does it impact budget/timeline?** | ✅ Yes | ❌ Rarely |
| **Is it hard to change later?** | ✅ Very | ❌ Easy to refactor |
| **Does it require business approval?** | ✅ Often | ❌ Rarely |
| **Can one developer decide alone?** | ❌ No | ✅ Yes |

---

## 2. Detailed Decision Mapping

### HLD Decisions (Architectural)

#### Technology Stack
```
Decision: "Should we use Python or Java?"

HLD because:
├─ Affects hiring (need Python developers)
├─ Affects performance characteristics
├─ Affects library ecosystem
├─ Affects deployment infrastructure
└─ Hard to change later (rewrite entire app)

Who decides: Architect + Engineering Manager
Timeline: Before development starts
Cost: Can't be easily reversed
```

#### Architecture Pattern
```
Decision: "Monolith vs Microservices?"

HLD because:
├─ Affects team structure (Conway's Law)
├─ Affects infrastructure costs
├─ Affects deployment complexity
├─ Affects debugging/monitoring
└─ Very expensive to change

Who decides: Architect + CTO
Timeline: Project inception
Cost: Changing = 6-12 months of work
```

#### Database Choice
```
Decision: "PostgreSQL vs MongoDB?"

HLD because:
├─ Affects data modeling approach
├─ Affects query patterns
├─ Affects scalability strategy
├─ Requires ops/infrastructure knowledge
└─ Migration is painful

Who decides: Architect + DBA + Manager
Timeline: Early design phase
Cost: Migration = weeks/months
```

#### API Design
```
Decision: "REST vs GraphQL vs gRPC?"

HLD because:
├─ Affects client integration
├─ Affects documentation approach
├─ Affects tooling choices
├─ Affects performance characteristics
└─ Breaking changes affect all clients

Who decides: Architect + Tech Lead
Timeline: Before building APIs
Cost: Changing = breaking changes for clients
```

---

### LLD Decisions (Implementation)

#### Data Structure Choice
```
Decision: "HashMap vs ArrayList for caching?"

LLD because:
├─ Affects only this one module
├─ Easy to change (refactor in hours)
├─ Developer understands trade-offs
├─ No external impact
└─ Performance can be measured and optimized

Who decides: Developer
Timeline: During implementation
Cost: Refactoring = 1-2 hours
```

#### Algorithm Implementation
```
Decision: "Bubble sort vs Quick sort?"

LLD because:
├─ Internal implementation detail
├─ Easy to swap algorithms
├─ No impact on API contract
├─ Can be optimized later
└─ Local to one function

Who decides: Developer
Timeline: While writing code
Cost: Refactoring = 30 minutes
```

#### Class Design
```
Decision: "How to structure the User class?"

LLD because:
├─ Internal to the module
├─ Can refactor without external impact
├─ Follows established patterns
├─ Affects code maintainability
└─ Changes don't ripple system-wide

Who decides: Developer (following conventions)
Timeline: During implementation
Cost: Refactoring = 2-4 hours
```

#### Error Handling Details
```
Decision: "Throw exception vs return error code?"

LLD because:
├─ Implementation detail
├─ Follows language idioms
├─ Local to module
├─ Can be refactored easily
└─ Standard patterns exist

Who decides: Developer (following team conventions)
Timeline: During implementation
Cost: Refactoring = 1 hour
```

---

## 3. Real-World Scenarios

### Scenario 1: Adding User Authentication

```
┌─────────────────────────────────────────────────┐
│              HLD Decisions                      │
└─────────────────────────────────────────────────┘

1. Authentication Strategy
   ├─ Session-based vs JWT vs OAuth2?
   ├─ Who: Architect + Security Team
   └─ Why HLD: Affects all clients, security model, infrastructure

2. Identity Provider
   ├─ Build custom vs Auth0 vs Cognito?
   ├─ Who: Architect + Manager (cost implications)
   └─ Why HLD: Vendor lock-in, cost, compliance

3. Session Storage
   ├─ Redis vs Memcached vs Database?
   ├─ Who: Architect
   └─ Why HLD: Infrastructure, ops, scalability

┌─────────────────────────────────────────────────┐
│              LLD Decisions                      │
└─────────────────────────────────────────────────┘

1. Password Hashing
   ├─ bcrypt vs Argon2 implementation details?
   ├─ Who: Developer (following security guidelines)
   └─ Why LLD: Implementation detail within security module

2. User Class Structure
   ├─ Fields, methods, validation logic?
   ├─ Who: Developer
   └─ Why LLD: Internal representation

3. Login Form Validation
   ├─ Client-side vs server-side validation order?
   ├─ Who: Developer
   └─ Why LLD: Implementation detail

4. Error Messages
   ├─ Specific wording of error messages?
   ├─ Who: Developer (with UX guidelines)
   └─ Why LLD: User-facing text, easy to change
```

---

### Scenario 2: Performance Optimization

```
Situation: "The system is slow!"

Step 1: Measure
├─ Identify bottleneck
└─ Quantify impact

Step 2: Classify Decision

Is it HLD if:
├─ Need to add caching layer (infrastructure)
├─ Need to change database (migration)
├─ Need to add CDN (ops/cost)
└─ Need to redesign API (breaking change)

Is it LLD if:
├─ Optimize algorithm (internal)
├─ Change data structure (local)
├─ Add indexes (database tuning)
└─ Cache method results (local optimization)

Example Decision Tree:
"Add caching to speed up API"
├─ Where to cache?
│   ├─ Application layer (LLD - local change)
│   ├─ Redis cluster (HLD - infrastructure)
│   └─ CDN (HLD - ops/cost)
└─ What to cache?
    ├─ Cache-Control headers (LLD - code change)
    └─ Cache invalidation strategy (HLD if complex)
```

---

## 4. EagleEye Case Study

Let's analyze actual decisions made in the EagleEye codebase:

### HLD Decisions in EagleEye

```python
# 1. Multi-Agent Architecture (HLD)
"""
Decision: Use 5 parallel specialist agents + synthesis

Why HLD:
- Defines entire system structure
- Affects all development work
- Impacts performance and cost
- Requires LangGraph framework knowledge
- Would take months to change to single-agent

Who decided: Architect
When: Project inception
"""

# 2. File-based Storage (HLD)
"""
Decision: Store reviews as files, not in database

Why HLD:
- Affects scalability limits
- Affects query capabilities
- Easy for v1, limits v2 scaling
- Migration to DB = weeks of work

Who decided: Architect + Manager (simplicity > scalability for v1)
When: Early design
"""

# 3. Both CLI and MCP Interfaces (HLD)
"""
Decision: Support both CLI and MCP server modes

Why HLD:
- Defines user interaction models
- Affects packaging and distribution
- Affects testing strategy
- Two codepaths to maintain

Who decided: Architect + Product Manager
When: Requirements phase
"""
```

### LLD Decisions in EagleEye

```python
# 1. Symbol Diff Algorithm (LLD)
"""
Decision: Use AST parsing for function change detection

Why LLD:
- Implementation detail of analysis module
- Can be swapped for regex-based approach
- Doesn't affect external APIs
- One developer can change it

Who decided: Developer
When: Implementing blast radius feature
"""

# 2. Rich Library for Terminal UI (LLD)
"""
Decision: Use Rich library for terminal formatting

Why LLD:
- Internal dependency choice
- Easy to swap for another library
- Affects only presentation layer
- No architectural impact

Who decided: Developer
When: Implementing terminal output
"""

# 3. Error Handling Pattern (LLD)
"""
Decision: Use try/except with specific exceptions

Why LLD:
- Standard Python idiom
- Local to each module
- Easy to refactor
- Follows team conventions

Who decided: Developer
When: Writing each module
"""
```

---

## 5. When to Escalate

### Developer → Tech Lead

Escalate when:
```
✅ Design pattern choice affects multiple modules
✅ Not sure which approach follows team standards
✅ Trade-off involves performance vs maintainability
✅ Need input on error handling strategy

Example:
"Should we use Factory pattern or Builder pattern for 
 creating ReviewResult objects?"
```

### Tech Lead → Architect

Escalate when:
```
✅ Design crosses team boundaries
✅ Requires new infrastructure/services
✅ Involves external dependencies
✅ Security or compliance implications

Example:
"Should we add a Redis cache for review results, or 
 is file-based storage sufficient?"
```

### Architect → Manager/CTO

Escalate when:
```
✅ Significant cost implications
✅ Affects product roadmap
✅ Vendor selection or licensing
✅ Team structure impact

Example:
"Moving to microservices will require 3 additional 
 engineers and 6 months. Proceed?"
```

---

## 6. Documentation Requirements

### HLD Documentation

```markdown
# Architecture Decision Record (ADR)

## Decision: Use Multi-Agent Architecture

### Context
We need to review PRs for multiple concerns: security, schema, 
pipeline, business logic, and code quality.

### Options Considered
1. Single sequential agent
2. Multi-agent parallel execution
3. Rule-based deterministic system (no AI)

### Decision
Multi-agent with parallel execution

### Rationale
- Faster (5x speedup via parallelism)
- Specialist expertise (focused prompts)
- Modular findings (clear attribution)

### Consequences
✅ Pros:
- Better quality reviews
- Faster execution
- Easy to add new specialists

❌ Cons:
- Higher API costs (5 agents = 5x calls)
- More complex orchestration
- Harder to debug

### Status
Accepted

### Date
2024-06-15

### Stakeholders
- @architect-name (decision maker)
- @manager-name (approved budget)
- @team-lead-name (implementation lead)
```

### LLD Documentation

```python
"""
Symbol Diff Module

Detects changes to functions, classes, and methods in a git diff.

Algorithm:
1. Parse Python files using AST
2. Extract function/class signatures
3. Compare old vs new signatures
4. Categorize changes (added, removed, modified, renamed)

Performance: O(n) where n = number of functions
Memory: O(n) to store AST

Author: developer-name
Date: 2024-06-20
"""

class SymbolDiff:
    """
    Analyzes symbol (function/class) changes in Python code.
    
    This is an internal implementation detail of the blast radius
    analysis. It can be refactored or replaced without affecting
    external APIs.
    """
    pass
```

---

## 💻 Practical Exercises

### Exercise 1: Classify These Decisions

Mark each as **HLD** or **LLD**:

1. [ ] Choosing between PostgreSQL and MongoDB
2. [ ] Deciding if a function should return None or raise an exception
3. [ ] Selecting AWS vs GCP for cloud hosting
4. [ ] Choosing variable names in a function
5. [ ] Deciding on microservices vs monolith architecture
6. [ ] Implementing bubble sort vs quick sort
7. [ ] Choosing REST vs GraphQL for APIs
8. [ ] Deciding if a class should use inheritance or composition
9. [ ] Selecting Redis vs Memcached for caching
10. [ ] Choosing between Snake_case and camelCase for variable names

**Answers:** See `exercises/solutions/day-3-exercise-1.md`

---

### Exercise 2: Design Decision Tree

For each scenario, create a decision tree showing HLD and LLD decisions:

**Scenario:** Adding real-time notifications to EagleEye

```
Your decision tree:

1. HLD Decisions:
   a. 
   b. 
   c. 

2. LLD Decisions:
   a. 
   b. 
   c. 

3. Who decides what:
   
   
4. Timeline:
   
```

**Solution:** See `exercises/solutions/day-3-exercise-2.md`

---

## 📝 Key Takeaways

- [ ] **HLD** = Architecture, affects system-wide concerns
- [ ] **LLD** = Implementation, affects local modules
- [ ] **HLD** mistakes are expensive, LLD mistakes are cheap
- [ ] **HLD** requires approval, LLD is developer autonomy
- [ ] **HLD** is hard to change, LLD is easy to refactor
- [ ] Know when to escalate decisions
- [ ] Document important HLD decisions (ADRs)

---

## 🔗 Next Steps

1. Complete the exercises above
2. Review 3 recent design decisions in your current project
3. Classify them as HLD or LLD
4. Move to Day 5-7: [System Design Basics](./03-system-design-basics.md)

---

## 📚 Additional Resources

- **ADR Templates**: [adr.github.io](https://adr.github.io/)
- **Case Studies**: Review open-source project architecture decisions
- **EagleEye**: Study this repo's architecture
