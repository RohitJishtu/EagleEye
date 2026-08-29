# Day 1-2: Software Design Principles

**Goal:** Understand fundamental principles that guide good software design  
**Time:** 2 days (4-6 hours total)

---

## 🎯 Learning Objectives

By the end of this section, you will:
- ✅ Understand and apply SOLID principles
- ✅ Recognize code smells and anti-patterns
- ✅ Write clean, maintainable code
- ✅ Make better design decisions

---

## 📖 Core Principles

### 1. SOLID Principles

#### **S - Single Responsibility Principle (SRP)**

> A class should have only one reason to change.

**Bad Example:**

```python
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
    
    def save_to_database(self):
        # Database logic
        pass
    
    def send_email(self):
        # Email logic
        pass
    
    def generate_report(self):
        # Report generation logic
        pass
```

**Problem:** This class has 3 reasons to change:
1. Database schema changes
2. Email service changes
3. Report format changes

**Good Example:**

```python
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email

class UserRepository:
    def save(self, user):
        # Database logic
        pass

class EmailService:
    def send_email(self, user):
        # Email logic
        pass

class ReportGenerator:
    def generate(self, user):
        # Report logic
        pass
```

**EagleEye Example:**

```python
# Good: Each module has one responsibility
eagleeye/
  ├─ integrations/github.py      # Only GitHub API
  ├─ integrations/anthropic.py   # Only Anthropic API
  ├─ analysis/blast_radius.py    # Only blast radius
  └─ presentation/terminal.py    # Only terminal output
```

---

#### **O - Open/Closed Principle (OCP)**

> Software entities should be open for extension, closed for modification.

**Bad Example:**

```python
class ReportGenerator:
    def generate(self, format):
        if format == "html":
            return self._generate_html()
        elif format == "pdf":
            return self._generate_pdf()
        elif format == "markdown":  # Added later - modified class!
            return self._generate_markdown()
```

**Problem:** Every new format requires modifying the class.

**Good Example:**

```python
from abc import ABC, abstractmethod

class ReportFormatter(ABC):
    @abstractmethod
    def format(self, data):
        pass

class HTMLFormatter(ReportFormatter):
    def format(self, data):
        return f"<html>{data}</html>"

class PDFFormatter(ReportFormatter):
    def format(self, data):
        return f"PDF: {data}"

class MarkdownFormatter(ReportFormatter):  # New formatter - no existing code modified!
    def format(self, data):
        return f"# {data}"

class ReportGenerator:
    def __init__(self, formatter: ReportFormatter):
        self.formatter = formatter
    
    def generate(self, data):
        return self.formatter.format(data)
```

**EagleEye Example:**

In EagleEye, you can add new specialist agents without modifying existing ones:

```python
# Adding a new agent doesn't require changing existing agents
def create_graph():
    agents = [
        schema_agent,
        security_agent,
        pipeline_agent,
        business_logic_agent,
        code_quality_agent,
        # NEW: Just add here, no other code changes!
        performance_agent,
    ]
```

---

#### **L - Liskov Substitution Principle (LSP)**

> Subtypes must be substitutable for their base types.

**Bad Example:**

```python
class Bird:
    def fly(self):
        return "Flying..."

class Penguin(Bird):  # Problem: Penguins can't fly!
    def fly(self):
        raise Exception("Penguins can't fly!")
```

**Problem:** You can't substitute Penguin for Bird without breaking the program.

**Good Example:**

```python
class Bird:
    pass

class FlyingBird(Bird):
    def fly(self):
        return "Flying..."

class Penguin(Bird):  # Penguin doesn't inherit fly()
    def swim(self):
        return "Swimming..."

class Sparrow(FlyingBird):
    pass
```

---

#### **I - Interface Segregation Principle (ISP)**

> Clients should not be forced to depend on interfaces they don't use.

**Bad Example:**

```python
class Worker:
    def work(self):
        pass
    
    def eat(self):
        pass
    
    def sleep(self):
        pass

class Robot(Worker):  # Problem: Robots don't eat or sleep!
    def work(self):
        return "Working..."
    
    def eat(self):
        raise NotImplementedError()
    
    def sleep(self):
        raise NotImplementedError()
```

**Good Example:**

```python
class Workable:
    def work(self):
        pass

class Eatable:
    def eat(self):
        pass

class Sleepable:
    def sleep(self):
        pass

class Human(Workable, Eatable, Sleepable):
    def work(self):
        return "Working..."
    
    def eat(self):
        return "Eating..."
    
    def sleep(self):
        return "Sleeping..."

class Robot(Workable):  # Only implements what it needs
    def work(self):
        return "Working..."
```

---

#### **D - Dependency Inversion Principle (DIP)**

> Depend on abstractions, not concretions.

**Bad Example:**

```python
class MySQLDatabase:
    def save(self, data):
        print(f"Saving to MySQL: {data}")

class UserService:
    def __init__(self):
        self.db = MySQLDatabase()  # Tightly coupled!
    
    def create_user(self, user):
        self.db.save(user)
```

**Problem:** Can't switch to PostgreSQL without modifying UserService.

**Good Example:**

```python
from abc import ABC, abstractmethod

class Database(ABC):
    @abstractmethod
    def save(self, data):
        pass

class MySQLDatabase(Database):
    def save(self, data):
        print(f"Saving to MySQL: {data}")

class PostgreSQLDatabase(Database):
    def save(self, data):
        print(f"Saving to PostgreSQL: {data}")

class UserService:
    def __init__(self, db: Database):  # Depends on abstraction
        self.db = db
    
    def create_user(self, user):
        self.db.save(user)

# Usage
mysql_service = UserService(MySQLDatabase())
postgres_service = UserService(PostgreSQLDatabase())
```

**EagleEye Example:**

```python
# EagleEye depends on abstractions
class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt):
        pass

# Can swap Anthropic for OpenAI without changing other code
class AnthropicProvider(LLMProvider):
    def generate(self, prompt):
        # Anthropic implementation
        pass

class OpenAIProvider(LLMProvider):
    def generate(self, prompt):
        # OpenAI implementation
        pass
```

---

### 2. DRY (Don't Repeat Yourself)

> Every piece of knowledge should have a single, unambiguous representation.

**Bad Example:**

```python
def calculate_order_total_usd(items):
    total = 0
    for item in items:
        total += item.price * item.quantity
    tax = total * 0.08
    return total + tax

def calculate_order_total_eur(items):
    total = 0
    for item in items:
        total += item.price * item.quantity
    tax = total * 0.20  # Different tax rate, but logic duplicated!
    return total + tax
```

**Good Example:**

```python
def calculate_order_total(items, tax_rate):
    total = sum(item.price * item.quantity for item in items)
    tax = total * tax_rate
    return total + tax

# Usage
usd_total = calculate_order_total(items, tax_rate=0.08)
eur_total = calculate_order_total(items, tax_rate=0.20)
```

---

### 3. KISS (Keep It Simple, Stupid)

> Simplicity should be a key goal; avoid unnecessary complexity.

**Bad Example:**

```python
def is_even(n):
    return True if n % 2 == 0 else False if n % 2 != 0 else None
```

**Good Example:**

```python
def is_even(n):
    return n % 2 == 0
```

**Another Bad Example (Over-engineering):**

```python
class AbstractFactoryProviderManagerBean:
    def create_instance_using_factory_pattern_with_dependency_injection(self):
        # Way too complex for a simple task!
        pass
```

**Good Example:**

```python
def create_user(name, email):
    return User(name, email)
```

---

### 4. YAGNI (You Aren't Gonna Need It)

> Don't build features until you actually need them.

**Bad Example:**

```python
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
        self.preferences = {}  # "We might need this later"
        self.settings = {}     # "Just in case"
        self.metadata = {}     # "Future-proofing"
        self.tags = []         # "Could be useful"
```

**Good Example:**

```python
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
    
    # Add other fields ONLY when you actually need them!
```

**When to add features:**
- ❌ "We might need this in 6 months"
- ❌ "It would be cool to have..."
- ✅ "This user story requires it NOW"
- ✅ "This bug can't be fixed without it"

---

## 🚫 Common Anti-Patterns

### 1. God Object

**Problem:** One class/object does everything.

```python
class Application:
    def handle_request(self):
        pass
    
    def save_to_database(self):
        pass
    
    def send_email(self):
        pass
    
    def generate_report(self):
        pass
    
    # 50 more methods...
```

**Solution:** Break into smaller, focused classes (see SRP).

---

### 2. Tight Coupling

**Problem:** Classes depend heavily on each other's internals.

```python
class OrderProcessor:
    def process(self, order):
        # Directly accessing another class's internals
        if order.user.account.balance >= order.total:
            order.user.account.balance -= order.total
```

**Solution:** Use interfaces and dependency injection.

---

### 3. Premature Optimization

**Problem:** Optimizing before you know there's a problem.

```python
# Bad: Optimizing before measuring
def get_user(user_id):
    # Added complex caching logic before knowing if it's slow!
    pass
```

**Solution:** Make it work first, measure, then optimize if needed.

---

## 💻 Practical Exercise

### Exercise 1: Identify Violations

Review this code and identify which principles are violated:

```python
class BlogPost:
    def __init__(self, title, content, author):
        self.title = title
        self.content = content
        self.author = author
    
    def save_to_mysql(self):
        connection = mysql.connect("localhost", "user", "password")
        connection.execute(f"INSERT INTO posts VALUES ('{self.title}', '{self.content}')")
    
    def send_notification_email(self):
        smtp = smtplib.SMTP('smtp.gmail.com', 587)
        smtp.send_message(f"New post: {self.title}")
    
    def render_html(self):
        return f"<h1>{self.title}</h1><p>{self.content}</p>"
    
    def render_markdown(self):
        return f"# {self.title}\n\n{self.content}"
```

**Violations:**
1. _______________ (Write your answer)
2. _______________ (Write your answer)
3. _______________ (Write your answer)

**Solution:** See `exercises/solutions/day-1-exercise-1.md`

---

### Exercise 2: Refactor This Code

Refactor this code to follow SOLID principles:

```python
class ShapeCalculator:
    def calculate_area(self, shape_type, dimensions):
        if shape_type == "circle":
            return 3.14 * dimensions["radius"] ** 2
        elif shape_type == "rectangle":
            return dimensions["width"] * dimensions["height"]
        elif shape_type == "triangle":
            return 0.5 * dimensions["base"] * dimensions["height"]
```

**Your refactored code:**

```python
# Write your refactored solution here




```

**Solution:** See `exercises/solutions/day-1-exercise-2.md`

---

## 📝 Key Takeaways

- [ ] **Single Responsibility**: One class, one job
- [ ] **Open/Closed**: Extend behavior without modifying code
- [ ] **Liskov Substitution**: Subtypes must be interchangeable
- [ ] **Interface Segregation**: Small, focused interfaces
- [ ] **Dependency Inversion**: Depend on abstractions
- [ ] **DRY**: Don't repeat logic
- [ ] **KISS**: Keep it simple
- [ ] **YAGNI**: Build only what you need now

---

## 🔗 Next Steps

1. Complete the exercises above
2. Review the EagleEye codebase and find examples of these principles
3. Move to Day 3-4: [HLD vs LLD](./02-hld-vs-lld.md)

---

## 📚 Additional Resources

- **Books**:
  - "Clean Code" by Robert C. Martin
  - "Design Patterns" by Gang of Four
  
- **Videos**:
  - [SOLID Principles Explained](https://www.youtube.com/results?search_query=solid+principles)
  
- **Articles**:
  - [SOLID Principles with Examples](https://www.digitalocean.com/community/conceptual_articles/s-o-l-i-d-the-first-five-principles-of-object-oriented-design)
