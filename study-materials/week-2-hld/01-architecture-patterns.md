# Week 2: High-Level Design (HLD) - Architecture Patterns

**Goal:** Master architectural patterns and system design  
**Duration:** 7 days

---

## 📚 Topics Covered

### Day 8-10: Architecture Patterns
- Monolithic Architecture
- Microservices Architecture
- Layered Architecture
- Event-Driven Architecture
- Serverless Architecture

### Day 11-13: Scalability & Reliability
- Load Balancing
- Caching Strategies
- Database Replication
- CAP Theorem
- Consistency Patterns

### Day 14: Practice Problems
- Design URL Shortener
- Design Twitter/X
- Design Instagram

---

## Day 8-10: Architecture Patterns

### 1. Monolithic Architecture

**Definition:** All components in a single,unified codebase and deployment unit.

```
┌─────────────────────────────────────┐
│         Monolith                    │
│                                     │
│  ┌───────────────────────────────┐ │
│  │    Presentation Layer         │ │
│  └───────────────────────────────┘ │
│  ┌───────────────────────────────┐ │
│  │    Business Logic Layer       │ │
│  └───────────────────────────────┘ │
│  ┌───────────────────────────────┐ │
│  │    Data Access Layer          │ │
│  └───────────────────────────────┘ │
│                                     │
└─────────────────────────────────────┘
           ↓
    Single Database
```

**Pros:**
- ✅ Simple to develop and test
- ✅ Easy to deploy (single unit)
- ✅ Good for small teams
- ✅ Low operational complexity

**Cons:**
- ❌ Scaling requires scaling entire app
- ❌ One bug can bring down everything
- ❌ Technology lock-in
- ❌ Slower CI/CD as app grows

**When to Use:**
- Small to medium applications
- MVP/prototypes
- Team < 10 developers
- Simple domain

**Example: EagleEye**

```python
# EagleEye is a well-designed monolith

eagleeye/           # Single codebase
  ├─ cli.py         # Entry point
  ├─ core/          # Business logic
  ├─ integrations/  # External services
  ├─ graphs/        # Agent orchestration
  └─ workflows/     # Review pipeline

# Benefits:
# - Easy to run: pip install, eagleeye review
# - Simple debugging: single process
# - Fast development: no distributed tracing needed
```

---

### 2. Microservices Architecture

**Definition:** Application split into small, independent services.

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   User      │  │   Order     │  │  Payment    │
│  Service    │  │  Service    │  │  Service    │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │
       ↓                ↓                ↓
  ┌─────────┐     ┌─────────┐     ┌─────────┐
  │User DB  │     │Order DB │     │Payment DB│
  └─────────┘     └─────────┘     └─────────┘
```

**Pros:**
- ✅ Independent scaling
- ✅ Technology diversity
- ✅ Fault isolation
- ✅ Team autonomy

**Cons:**
- ❌ Complex deployment
- ❌ Distributed tracing needed
- ❌ Network latency
- ❌ Data consistency challenges

**When to Use:**
- Large applications
- Multiple teams
- Need independent scaling
- Different technology requirements

**Example: How EagleEye Could Become Microservices**

```
# If EagleEye grows to SaaS platform:

┌─────────────────┐
│   API Gateway   │
└────────┬────────┘
         │
    ┌────┴───────────────┐
    │                    │
┌───▼──────┐      ┌─────▼──────┐
│ GitHub   │      │  Review    │
│ Service  │      │  Service   │
└──────────┘      └─────┬──────┘
                        │
            ┌───────────┼──────────┐
            │           │          │
      ┌─────▼────┐ ┌───▼────┐ ┌──▼─────┐
      │ Schema   │ │Security│ │Pipeline│
      │ Agent    │ │ Agent  │ │ Agent  │
      └──────────┘ └────────┘ └────────┘
```

---

### 3. Layered Architecture

**Definition:** Organize code into horizontal layers with specific responsibilities.

```
┌───────────────────────────────────┐
│   Presentation Layer              │  ← UI, API controllers
├───────────────────────────────────┤
│   Business Logic Layer            │  ← Domain logic
├───────────────────────────────────┤
│   Data Access Layer               │  ← Database queries
├───────────────────────────────────┤
│   Database                        │  ← Persistence
└───────────────────────────────────┘
```

**Rules:**
- Each layer only talks to the layer below
- No skipping layers
- Clear separation of concerns

**EagleEye Example:**

```python
# Presentation Layer
eagleeye/presentation/
  ├─ terminal.py          # Terminal output
  └─ html/report.py       # HTML reports

# Business Logic Layer
eagleeye/graphs/
  ├─ multi_agent/         # Agent orchestration
  └─ workflows/           # Review workflow

# Data Access Layer
eagleeye/integrations/
  ├─ github.py            # GitHub API
  └─ anthropic.py         # Anthropic API

# Storage Layer
reviews/                  # File system
```

---

### 4. Event-Driven Architecture

**Definition:** Components communicate through events.

```
  Event Producer              Event Bus              Event Consumers
┌──────────────┐           ┌──────────┐         ┌─────────────────┐
│   Order      │──Event──→ │  Kafka/  │──Event→ │ Email Service   │
│   Service    │           │  RabbitMQ│         └─────────────────┘
└──────────────┘           └──────────┘         ┌─────────────────┐
                                        └─Event→ │Inventory Service│
                                                 └─────────────────┘
```

**Pros:**
- ✅ Loose coupling
- ✅ Asynchronous processing
- ✅ Easy to add new consumers
- ✅ Scalable

**Cons:**
- ❌ Harder to debug (async)
- ❌ Eventual consistency
- ❌ Requires message broker
- ❌ Complex error handling

**Example: EagleEye Could Use Events**

```python
# Potential future enhancement

# When PR review completes:
event = {
    "type": "review.completed",
    "pr": "owner/repo#42",
    "verdict": "APPROVE",
    "findings": [...]
}

# Consumers:
# 1. Jira integration → create ticket for critical findings
# 2. Slack integration → notify team
# 3. Analytics service → record metrics
# 4. GitHub integration → post comment
```

---

### 5. Serverless Architecture

**Definition:** Run code without managing servers (FaaS - Functions as a Service).

```
API Request
    ↓
┌────────────────┐
│  API Gateway   │
└───────┬────────┘
        │
   ┌────┴─────┐
   │          │
┌──▼────┐ ┌──▼────┐
│Lambda │ │Lambda │
│ Func 1│ │ Func 2│
└───────┘ └───────┘
```

**Pros:**
- ✅ No server management
- ✅ Auto-scaling
- ✅ Pay per execution
- ✅ Fast deployment

**Cons:**
- ❌ Cold start latency
- ❌ Vendor lock-in
- ❌ Limited execution time
- ❌ Debugging harder

**Example: EagleEye as Serverless**

```python
# Lambda function for PR review

def lambda_handler(event, context):
    """
    Triggered by GitHub webhook when PR is opened
    """
    pr_url = event['pull_request']['url']
    
    # Run review
    result = review_pr(pr_url)
    
    # Post comment
    post_github_comment(pr_url, result)
    
    return {"statusCode": 200}
```

---

## Choosing the Right Architecture

### Decision Matrix

| Factor | Monolith | Microservices | Serverless |
|--------|----------|---------------|------------|
| **Team Size** | < 10 | > 20 | Any |
| **Complexity** | Low-Medium | High | Low-Medium |
| **Scalability** | Vertical | Horizontal | Auto |
| **Ops Overhead** | Low | High | Very Low |
| **Cost (small scale)** | $ | $$$ | $ |
| **Cost (large scale)** | $$$ | $$ | $$ |
| **Time to Market** | Fast | Slow | Fast |

### When to Choose Each

**Choose Monolith if:**
- Team < 10 developers
- Application is not complex
- Need fast time to market
- Limited ops resources

**Choose Microservices if:**
- Large team (multiple teams)
- Complex domain
- Need independent scaling
- Different technology needs

**Choose Serverless if:**
- Event-driven workload
- Unpredictable traffic
- Want zero ops overhead
- Pay-per-use makes sense

---

## 💻 Practice Exercise

### Exercise 1: Design an E-commerce System

**Requirements:**
- Users can browse products
- Add items to cart
- Checkout and pay
- Track order status
- Admin can manage inventory

**Your Task:**

1. Choose an architecture (Monolith, Microservices, or Hybrid)
2. Draw the architecture diagram
3. List components/services
4. Explain your choice

**Solution Template:**

```
Architecture Choice: _____________

Reason:




Diagram:




Components:
1. 
2. 
3. 

Trade-offs:
Pros:
-
-

Cons:
-
-
```

**Solution:** See `exercises/solutions/week-2-exercise-1.md`

---

## 📝 Key Takeaways

- [ ] **Monolith**: Simple, good for small teams
- [ ] **Microservices**: Complex, good for large organizations
- [ ] **Layered**: Separates concerns horizontally
- [ ] **Event-Driven**: Loose coupling, async communication
- [ ] **Serverless**: No ops, auto-scaling
- [ ] **No silver bullet**: Choose based on context

---

## 🔗 Next Topics

- [Scalability Patterns](./02-scalability-patterns.md)
- [Distributed Systems](./03-distributed-systems.md)
- [Data Storage Strategies](./04-data-storage.md)

---

## 📚 Resources

- Martin Fowler's Blog on Architecture
- "Building Microservices" by Sam Newman
- "Designing Data-Intensive Applications" by Martin Kleppmann
