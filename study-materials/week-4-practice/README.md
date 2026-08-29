# Week 4: Practice Problems & Mock Interviews

**Goal:** Apply HLD and LLD skills to realistic problems  
**Duration:** 7 days

---

## 📚 Overview

This week focuses on:
- Solving complete system design problems
- Mock interview practice
- Real-world case studies
- Building confidence

---

## Day 22-24: HLD Practice Problems

### Problem 1: Design URL Shortener (like bit.ly)

**Difficulty:** Medium  
**Time:** 45 minutes

#### Requirements

**Functional:**
- Generate short URL from long URL
- Redirect short URL to original URL
- Custom short URLs (optional)
- Analytics (click count, geography)
- URL expiration

**Non-Functional:**
- High availability (99.9% uptime)
- Low latency (< 100ms redirect)
- Handle 100M URLs
- 1000 requests/second

#### Solution Template

```
1. Requirements Clarification (5 min)
   - Ask questions to understand scope
   
2. Capacity Estimation (5 min)
   - Storage: 100M URLs × 1KB = 100GB
   - Bandwidth: 1000 req/s × 1KB = 1MB/s
   - Cache: 20% of URLs (80/20 rule) = 20GB

3. API Design (5 min)
   POST /api/shorten
   Body: { "long_url": "https://example.com/very/long/url" }
   Response: { "short_url": "https://short.ly/abc123" }
   
   GET /abc123
   → Redirect to long URL

4. Database Design (10 min)
   Table: urls
   - id (PK)
   - short_code (unique index)
   - long_url
   - user_id
   - created_at
   - expires_at
   - click_count

5. High-Level Architecture (15 min)
   
   [Draw diagram]
   
   Client → Load Balancer → API Servers → Cache (Redis) → Database
                                        ↓
                                   Analytics Queue

6. Algorithm (5 min)
   - Base62 encoding (a-z, A-Z, 0-9)
   - Generate 7-char codes = 62^7 = 3.5 trillion URLs
   - Hash function: MD5(long_url) → take first 7 chars
   - Handle collisions: append counter

7. Trade-offs & Scale (remaining time)
   - Use Redis for hot URLs
   - Database sharding by hash(short_code)
   - CDN for global low latency
```

#### Your Solution

```
[Draw your architecture diagram here]

[Write your notes]









```

**Model Solution:** See `week-4-practice/solutions/url-shortener.md`

---

### Problem 2: Design Twitter/X

**Difficulty:** Hard  
**Time:** 45 minutes

#### Requirements

**Functional:**
- Post tweets (280 chars)
- Follow/unfollow users
- Timeline (home feed showing tweets from people you follow)
- Like, retweet, reply
- Trending topics
- Notifications

**Non-Functional:**
- 500M users
- 300M DAU (Daily Active Users)
- 200M tweets per day
- Timeline load < 500ms
- High availability

#### Approach

```
1. Requirements (5 min)
   - Prioritize features
   - Read-heavy or write-heavy? (Read-heavy: 100:1 ratio)

2. Capacity (5 min)
   - Storage: 200M tweets/day × 1KB × 365 days × 5 years = 365TB
   - Timeline requests: 300M users × 10 refreshes/day = 3B requests/day
   - Peak load: 3B / 86400 = 35K requests/second

3. API Design (5 min)
   POST /api/tweet
   GET /api/timeline/{user_id}
   POST /api/follow/{user_id}
   GET /api/trending

4. Database Schema (10 min)
   
   users: id, username, email, bio, created_at
   
   tweets: id, user_id, content, created_at, like_count, retweet_count
   
   follows: follower_id, followee_id, created_at
   
   timeline_cache: user_id, tweet_ids (pre-computed)

5. Architecture (15 min)
   
   Key Components:
   - API Gateway
   - Tweet Service
   - Timeline Service
   - Follow Service
   - Notification Service
   - Search Service (Elasticsearch)
   
   Data Stores:
   - PostgreSQL (users, follows)
   - Cassandra (tweets - distributed)
   - Redis (timeline cache, trending topics)
   - S3 (media storage)

6. Key Design Decisions (10 min)
   
   Timeline Generation:
   - Fan-out on write: Pre-compute timelines when tweet is posted
   - Fan-out on read: Compute timeline when user requests it
   - Hybrid: Fan-out for regular users, on-read for celebrities
   
   Why hybrid?
   - Celebrity with 100M followers → too expensive to fan-out to all
   - Regular user: fast reads with fan-out on write
```

#### Your Solution

```
[Your architecture and notes]













```

**Model Solution:** See `week-4-practice/solutions/twitter-design.md`

---

### Problem 3: Design Netflix

**Difficulty:** Hard  
**Time:** 45 minutes

#### Requirements

**Functional:**
- Video streaming
- Search catalog
- Recommendations
- User profiles
- Resume playback
- Download for offline

**Non-Functional:**
- 200M users
- 100M concurrent streams
- Video sizes: 500MB (SD) to 5GB (4K)
- Low latency streaming
- 99.99% availability

#### Key Challenges

1. **Video Storage & CDN**
   - Transcode videos to multiple formats (1080p, 720p, 480p)
   - Store in S3
   - Distribute via CDN (CloudFront, Akamai)

2. **Adaptive Bitrate Streaming**
   - Switch quality based on network speed
   - Use HLS or DASH protocol

3. **Recommendation System**
   - ML model (collaborative filtering)
   - Real-time personalization
   - Batch processing for recommendations

4. **Scalability**
   - Microservices architecture
   - Database sharding
   - Caching (Redis)

#### Your Solution

```
[Your complete design]















```

**Model Solution:** See `week-4-practice/solutions/netflix-design.md`

---

## Day 22-24: LLD Practice Problems

### Problem 1: Design Parking Lot System

**Difficulty:** Medium  
**Time:** 45 minutes

#### Requirements

- Multiple levels
- Different spot sizes (compact, regular, large)
- Entry/exit gates
- Pricing based on time
- Spot assignment algorithm

#### Solution Approach

```python
# Key Classes

class ParkingLot:
    def __init__(self, levels):
        self.levels = levels
    
    def park_vehicle(self, vehicle):
        # Find spot and assign
        pass
    
    def unpark_vehicle(self, ticket):
        # Free spot and calculate fee
        pass

class Level:
    def __init__(self, spots):
        self.spots = spots
    
    def find_available_spot(self, vehicle_size):
        # Return available spot or None
        pass

class ParkingSpot:
    def __init__(self, spot_number, size):
        self.spot_number = spot_number
        self.size = size  # COMPACT, REGULAR, LARGE
        self.vehicle = None
        self.is_available = True
    
    def park(self, vehicle):
        self.vehicle = vehicle
        self.is_available = False
    
    def unpark(self):
        self.vehicle = None
        self.is_available = True

class Vehicle:
    def __init__(self, license_plate, size):
        self.license_plate = license_plate
        self.size = size

class Ticket:
    def __init__(self, ticket_number, vehicle, spot, entry_time):
        self.ticket_number = ticket_number
        self.vehicle = vehicle
        self.spot = spot
        self.entry_time = entry_time

# Design Patterns Used:
# - Singleton: ParkingLot (only one parking lot)
# - Strategy: Pricing strategy (hourly, daily, monthly)
# - Factory: Vehicle factory (Car, Truck, Motorcycle)
```

#### Your Implementation

```python
# Complete the implementation








```

**Full Solution:** See `week-4-practice/solutions/parking-lot.py`

---

### Problem 2: Design Elevator System

**Difficulty:** Medium  
**Time:** 45 minutes

#### Requirements

- Multiple elevators
- Efficient request handling
- Direction-based scheduling (SCAN algorithm)
- Emergency mode
- Load balancing

#### Key Design Decisions

```python
class ElevatorSystem:
    def __init__(self, num_elevators, num_floors):
        self.elevators = [Elevator(i) for i in range(num_elevators)]
        self.scheduler = ElevatorScheduler(self.elevators)
    
    def request_elevator(self, from_floor, direction):
        # Find best elevator using scheduling algorithm
        elevator = self.scheduler.schedule(from_floor, direction)
        elevator.add_request(from_floor)

class Elevator:
    def __init__(self, elevator_id):
        self.elevator_id = elevator_id
        self.current_floor = 0
        self.direction = Direction.IDLE
        self.requests = []  # Priority queue
    
    def move(self):
        # Move to next floor based on requests
        pass
    
    def open_door(self):
        pass
    
    def close_door(self):
        pass

class ElevatorScheduler:
    """
    SCAN Algorithm:
    - Choose elevator moving in same direction as request
    - If none, choose closest idle elevator
    - If none idle, choose elevator that will return soonest
    """
    def schedule(self, floor, direction):
        # Implementation
        pass

# Design Patterns:
# - State Pattern: Elevator states (Moving, Idle, Stopped)
# - Strategy Pattern: Different scheduling algorithms
# - Observer Pattern: Notify when elevator arrives
```

#### Your Implementation

```python
# Your code here








```

**Full Solution:** See `week-4-practice/solutions/elevator-system.py`

---

## Day 25-26: Mock Interviews

### Mock Interview Guidelines

#### Preparation (Before Interview)

1. **Set up environment**
   - Whiteboard or drawing tool
   - Code editor
   - Timer (45 minutes)

2. **Review common patterns**
   - Caching, load balancing, sharding
   - Design patterns
   - Trade-offs

#### During Interview (45 minutes)

**Timing breakdown:**
- 5 min: Requirements clarification
- 5 min: Capacity estimation
- 5 min: API design
- 10 min: Database schema
- 15 min: Architecture diagram
- 5 min: Trade-offs & scaling

#### Common Mistakes to Avoid

❌ **Don't:**
- Jump to solution without clarifying requirements
- Forget to discuss trade-offs
- Ignore scaling concerns
- Use technologies you don't understand
- Be silent (think out loud!)

✅ **Do:**
- Ask clarifying questions
- Start simple, then iterate
- Discuss trade-offs explicitly
- Consider failure scenarios
- Communicate clearly

### Mock Interview Problems

1. **Design WhatsApp** (45 min)
2. **Design Uber** (45 min)
3. **Design Amazon** (45 min)
4. **Design YouTube** (45 min)
5. **Design Instagram** (45 min)

**Solutions:** See `week-4-practice/mock-interviews/` folder

---

## Day 27-28: Case Studies

### Case Study 1: Analyze EagleEye Architecture

Review this repository and answer:

1. **What architecture pattern does it use?**
2. **What are the main components?**
3. **What design patterns can you identify?**
4. **What are the trade-offs made?**
5. **How would you scale it to SaaS?**

**Your Analysis:**

```
1. Architecture Pattern:



2. Components:



3. Design Patterns:



4. Trade-offs:



5. Scaling Strategy:



```

---

### Case Study 2: Real Production System

Pick an open-source project and analyze:

**Suggestions:**
- Django (web framework)
- Redis (in-memory database)
- Kubernetes (orchestration)
- FastAPI (web framework)

**Analysis Template:**

```
Project: _________________

HLD Analysis:
- Architecture style:
- Key components:
- Integration points:
- Scalability approach:

LLD Analysis:
- Design patterns used:
- Code organization:
- Error handling:
- Testing strategy:

Key Learnings:
1.
2.
3.
```

---

## 📝 Final Checklist

After completing Week 4, you should be able to:

### HLD Skills
- [ ] Design a system in 45 minutes
- [ ] Estimate capacity requirements
- [ ] Choose appropriate databases
- [ ] Design scalable architectures
- [ ] Discuss trade-offs confidently
- [ ] Draw clear architecture diagrams

### LLD Skills
- [ ] Apply design patterns appropriately
- [ ] Design clean class hierarchies
- [ ] Write SOLID-compliant code
- [ ] Handle concurrency properly
- [ ] Create maintainable code
- [ ] Explain implementation choices

### Interview Skills
- [ ] Ask good clarifying questions
- [ ] Think out loud
- [ ] Start simple, iterate
- [ ] Handle feedback gracefully
- [ ] Manage time effectively

---

## 🎉 Congratulations!

You've completed the 4-week System Design Study Plan!

**Next Steps:**
1. Keep practicing (1-2 problems per week)
2. Read engineering blogs
3. Contribute to open-source
4. Build side projects
5. Mentor others

**Remember:** System design is a skill that improves with practice!

---

**Resources:**
- [Practice Problems Bank](./practice-problems/)
- [Mock Interview Guide](./mock-interviews/)
- [Case Studies](./case-studies/)
