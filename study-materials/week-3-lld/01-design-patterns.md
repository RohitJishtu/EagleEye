# Week 3: Low-Level Design (LLD) - Design Patterns

**Goal:** Master design patterns and object-oriented design  
**Duration:** 7 days

---

## 📚 Topics Covered

### Day 15-17: Design Patterns
- Creational Patterns (Singleton, Factory, Builder)
- Structural Patterns (Adapter, Decorator, Proxy)
- Behavioral Patterns (Observer, Strategy, Command)

### Day 18-20: Object-Oriented Design
- Class Design
- Inheritance vs Composition
- Polymorphism
- Interface Design

### Day 21: Practice Problems
- Design Parking Lot
- Design Elevator System
- Design Library Management System

---

## Day 15-17: Design Patterns

### Creational Patterns

#### 1. Singleton Pattern

**Purpose:** Ensure only one instance of a class exists.

**When to Use:**
- Database connections
- Configuration managers
- Logging services

**Implementation:**

```python
class DatabaseConnection:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        self.connection = "Connected to DB"
    
    def query(self, sql):
        return f"Executing: {sql}"

# Usage
db1 = DatabaseConnection()
db2 = DatabaseConnection()

assert db1 is db2  # Same instance!
```

**Pros:**
- ✅ Controlled access to single instance
- ✅ Lazy initialization
- ✅ Global access point

**Cons:**
- ❌ Hard to test (global state)
- ❌ Violates Single Responsibility
- ❌ Can hide dependencies

**EagleEye Example:**

```python
# Configuration singleton
class Config:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.load_config()
        return cls._instance
    
    def load_config(self):
        # Load from .env, config.yml, etc.
        pass

# Used throughout the application
config = Config()
```

---

#### 2. Factory Pattern

**Purpose:** Create objects without specifying exact class.

**When to Use:**
- Object creation is complex
- Need to create different types based on input
- Want to decouple creation from usage

**Implementation:**

```python
from abc import ABC, abstractmethod

class Animal(ABC):
    @abstractmethod
    def speak(self):
        pass

class Dog(Animal):
    def speak(self):
        return "Woof!"

class Cat(Animal):
    def speak(self):
        return "Meow!"

class AnimalFactory:
    @staticmethod
    def create_animal(animal_type: str) -> Animal:
        if animal_type == "dog":
            return Dog()
        elif animal_type == "cat":
            return Cat()
        else:
            raise ValueError(f"Unknown animal: {animal_type}")

# Usage
factory = AnimalFactory()
dog = factory.create_animal("dog")
print(dog.speak())  # "Woof!"
```

**EagleEye Example:**

```python
class AgentFactory:
    """Create specialist agents based on type"""
    
    @staticmethod
    def create_agent(agent_type: str):
        if agent_type == "schema":
            return SchemaAgent()
        elif agent_type == "security":
            return SecurityAgent()
        elif agent_type == "pipeline":
            return PipelineAgent()
        else:
            raise ValueError(f"Unknown agent: {agent_type}")

# Usage in graph setup
agents = [
    AgentFactory.create_agent("schema"),
    AgentFactory.create_agent("security"),
    AgentFactory.create_agent("pipeline"),
]
```

---

#### 3. Builder Pattern

**Purpose:** Construct complex objects step by step.

**When to Use:**
- Object has many optional parameters
- Construction process is complex
- Want immutable objects

**Implementation:**

```python
class Computer:
    def __init__(self):
        self.cpu = None
        self.ram = None
        self.storage = None
        self.gpu = None
    
    def __str__(self):
        return f"CPU: {self.cpu}, RAM: {self.ram}GB, Storage: {self.storage}GB, GPU: {self.gpu}"

class ComputerBuilder:
    def __init__(self):
        self.computer = Computer()
    
    def set_cpu(self, cpu):
        self.computer.cpu = cpu
        return self  # Return self for chaining
    
    def set_ram(self, ram):
        self.computer.ram = ram
        return self
    
    def set_storage(self, storage):
        self.computer.storage = storage
        return self
    
    def set_gpu(self, gpu):
        self.computer.gpu = gpu
        return self
    
    def build(self):
        return self.computer

# Usage - fluent interface
computer = (ComputerBuilder()
    .set_cpu("Intel i7")
    .set_ram(16)
    .set_storage(512)
    .set_gpu("NVIDIA RTX 3080")
    .build())

print(computer)
```

**EagleEye Example:**

```python
class ReviewPayloadBuilder:
    """Build complex review payload step by step"""
    
    def __init__(self):
        self.payload = {}
    
    def add_pr_info(self, owner, repo, pr_number):
        self.payload["pr"] = f"{owner}/{repo}#{pr_number}"
        return self
    
    def add_diff(self, diff):
        self.payload["diff"] = diff
        return self
    
    def add_blast_radius(self, blast):
        self.payload["blast_radius"] = blast
        return self
    
    def add_schema_impact(self, schema):
        self.payload["schema_impact"] = schema
        return self
    
    def build(self):
        return self.payload

# Usage
payload = (ReviewPayloadBuilder()
    .add_pr_info("owner", "repo", 42)
    .add_diff(diff_content)
    .add_blast_radius(blast_result)
    .add_schema_impact(schema_result)
    .build())
```

---

### Structural Patterns

#### 4. Adapter Pattern

**Purpose:** Make incompatible interfaces work together.

**When to Use:**
- Integrating with third-party libraries
- Legacy code integration
- Multiple implementations of same concept

**Implementation:**

```python
# Target interface we want
class MediaPlayer:
    def play(self, filename):
        pass

# Existing incompatible class
class VLCPlayer:
    def play_vlc(self, filename):
        print(f"Playing {filename} with VLC")

# Adapter
class VLCAdapter(MediaPlayer):
    def __init__(self):
        self.vlc = VLCPlayer()
    
    def play(self, filename):
        # Adapt VLC's interface to MediaPlayer
        self.vlc.play_vlc(filename)

# Usage
player = VLCAdapter()
player.play("video.mp4")  # Works with MediaPlayer interface!
```

**EagleEye Example:**

```python
# Adapter for different LLM providers

class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        pass

class AnthropicAdapter(LLMProvider):
    def __init__(self, api_key):
        self.client = anthropic.Anthropic(api_key=api_key)
    
    def generate(self, prompt: str) -> str:
        response = self.client.messages.create(
            model="claude-sonnet-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

class OpenAIAdapter(LLMProvider):
    def __init__(self, api_key):
        self.client = openai.OpenAI(api_key=api_key)
    
    def generate(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content

# Usage - same interface!
llm = AnthropicAdapter(api_key)
# or
llm = OpenAIAdapter(api_key)

result = llm.generate("Review this PR")  # Works with both!
```

---

#### 5. Decorator Pattern

**Purpose:** Add behavior to objects dynamically.

**When to Use:**
- Add features without modifying original class
- Multiple combinations of features
- Need to add/remove features at runtime

**Implementation:**

```python
class Coffee:
    def cost(self):
        return 5
    
    def description(self):
        return "Coffee"

class MilkDecorator:
    def __init__(self, coffee):
        self._coffee = coffee
    
    def cost(self):
        return self._coffee.cost() + 2
    
    def description(self):
        return self._coffee.description() + " + Milk"

class SugarDecorator:
    def __init__(self, coffee):
        self._coffee = coffee
    
    def cost(self):
        return self._coffee.cost() + 1
    
    def description(self):
        return self._coffee.description() + " + Sugar"

# Usage
coffee = Coffee()
print(coffee.description(), coffee.cost())  # "Coffee" 5

coffee_with_milk = MilkDecorator(coffee)
print(coffee_with_milk.description(), coffee_with_milk.cost())  # "Coffee + Milk" 7

coffee_deluxe = SugarDecorator(MilkDecorator(Coffee()))
print(coffee_deluxe.description(), coffee_deluxe.cost())  # "Coffee + Milk + Sugar" 8
```

---

### Behavioral Patterns

#### 6. Observer Pattern

**Purpose:** Notify multiple objects when state changes.

**When to Use:**
- Event handling systems
- Pub/sub messaging
- MVC frameworks

**Implementation:**

```python
class Subject:
    def __init__(self):
        self._observers = []
        self._state = None
    
    def attach(self, observer):
        self._observers.append(observer)
    
    def detach(self, observer):
        self._observers.remove(observer)
    
    def notify(self):
        for observer in self._observers:
            observer.update(self._state)
    
    def set_state(self, state):
        self._state = state
        self.notify()

class Observer:
    def update(self, state):
        print(f"Observer notified: {state}")

# Usage
subject = Subject()
observer1 = Observer()
observer2 = Observer()

subject.attach(observer1)
subject.attach(observer2)

subject.set_state("New State!")  # Both observers notified
```

**EagleEye Example:**

```python
class ReviewProgress:
    """Notify listeners of review progress"""
    
    def __init__(self):
        self._listeners = []
    
    def subscribe(self, listener):
        self._listeners.append(listener)
    
    def notify_started(self, pr):
        for listener in self._listeners:
            listener.on_review_started(pr)
    
    def notify_agent_complete(self, agent_name, result):
        for listener in self._listeners:
            listener.on_agent_complete(agent_name, result)
    
    def notify_complete(self, review):
        for listener in self._listeners:
            listener.on_review_complete(review)

class TerminalProgressListener:
    def on_review_started(self, pr):
        print(f"🔍 Reviewing PR #{pr}")
    
    def on_agent_complete(self, agent_name, result):
        print(f"✅ {agent_name} agent complete")
    
    def on_review_complete(self, review):
        print(f"🎉 Review complete: {review.verdict}")

# Usage
progress = ReviewProgress()
progress.subscribe(TerminalProgressListener())
progress.subscribe(SlackNotificationListener())
```

---

#### 7. Strategy Pattern

**Purpose:** Define a family of algorithms and make them interchangeable.

**When to Use:**
- Multiple ways to do something
- Want to switch algorithms at runtime
- Avoid conditional logic

**Implementation:**

```python
from abc import ABC, abstractmethod

class SortStrategy(ABC):
    @abstractmethod
    def sort(self, data):
        pass

class BubbleSort(SortStrategy):
    def sort(self, data):
        print("Sorting using bubble sort")
        return sorted(data)  # Simplified

class QuickSort(SortStrategy):
    def sort(self, data):
        print("Sorting using quick sort")
        return sorted(data)  # Simplified

class Sorter:
    def __init__(self, strategy: SortStrategy):
        self.strategy = strategy
    
    def sort_data(self, data):
        return self.strategy.sort(data)

# Usage
data = [3, 1, 4, 1, 5, 9, 2, 6]

sorter = Sorter(BubbleSort())
sorter.sort_data(data)

sorter.strategy = QuickSort()  # Change strategy at runtime!
sorter.sort_data(data)
```

**EagleEye Example:**

```python
class ReportFormatter(ABC):
    @abstractmethod
    def format(self, review_result):
        pass

class MarkdownFormatter(ReportFormatter):
    def format(self, review_result):
        return f"# Review\n\n{review_result.summary}"

class HTMLFormatter(ReportFormatter):
    def format(self, review_result):
        return f"<h1>Review</h1><p>{review_result.summary}</p>"

class JSONFormatter(ReportFormatter):
    def format(self, review_result):
        return json.dumps(review_result.to_dict())

class ReportGenerator:
    def __init__(self, formatter: ReportFormatter):
        self.formatter = formatter
    
    def generate(self, review_result):
        return self.formatter.format(review_result)

# Usage
review = perform_review(pr)

# Generate different formats
md_report = ReportGenerator(MarkdownFormatter()).generate(review)
html_report = ReportGenerator(HTMLFormatter()).generate(review)
json_report = ReportGenerator(JSONFormatter()).generate(review)
```

---

## 💻 Practice Exercises

### Exercise 1: Implement Patterns

Implement these design patterns:

1. **Singleton:** Create a Logger class
2. **Factory:** Create a ShapeFactory (Circle, Square, Triangle)
3. **Observer:** Create a stock price notification system
4. **Strategy:** Create a payment processor (CreditCard, PayPal, Bitcoin)

**Template:**

```python
# Exercise 1: Singleton Logger
class Logger:
    # Your implementation here
    pass


# Exercise 2: Factory for Shapes
class Shape(ABC):
    # Your implementation here
    pass


# Exercise 3: Observer for Stock Prices
class StockPrice:
    # Your implementation here
    pass


# Exercise 4: Strategy for Payments
class PaymentStrategy(ABC):
    # Your implementation here
    pass
```

**Solutions:** See `exercises/solutions/week-3-exercises.py`

---

### Exercise 2: Pattern Recognition

Identify which pattern to use for each scenario:

1. You need to ensure only one database connection exists
2. You want to add logging to multiple classes without modifying them
3. You need to notify multiple UIs when data changes
4. You want to create different types of documents (PDF, Word, HTML)
5. You need to make an old API work with your new code

**Answers:**
1. _____________
2. _____________
3. _____________
4. _____________
5. _____________

---

## 📝 Key Takeaways

- [ ] **Creational**: How objects are created (Singleton, Factory, Builder)
- [ ] **Structural**: How objects are composed (Adapter, Decorator, Proxy)
- [ ] **Behavioral**: How objects communicate (Observer, Strategy, Command)
- [ ] **Don't overuse**: Patterns solve specific problems
- [ ] **Know trade-offs**: Each pattern has pros and cons

---

## 🔗 Next Topics

- [Object-Oriented Principles](./02-oop-principles.md)
- [SOLID Principles Deep Dive](./03-solid-principles.md)
- [Concurrency Patterns](./04-concurrency.md)

---

## 📚 Resources

- "Design Patterns" by Gang of Four
- "Head First Design Patterns" (easier to read)
- Refactoring.Guru (excellent visual explanations)
