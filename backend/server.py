from fastapi import FastAPI, APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timedelta
import bcrypt
import jwt
from enum import Enum
import asyncio

# Import our custom modules
from websocket_manager import manager
from auction_timer import auction_timer
from achievements import achievement_manager, Achievement
from scoring import PerformanceStats, calculate_points

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI(title="SportX Cricket Auction API", version="1.0.0")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBearer()
SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# Enums
class TournamentStatus(str, Enum):
    DRAFT = "draft"
    SETUP = "setup"
    AUCTION_SCHEDULED = "auction_scheduled"
    AUCTION_LIVE = "auction_live"
    ACTIVE = "active"
    COMPLETED = "completed"

class PlayerPosition(str, Enum):
    BATSMAN = "Batsman"
    BOWLER = "Bowler"
    ALL_ROUNDER = "All Rounder"
    WICKET_KEEPER = "Wicket Keeper"

class InviteStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"

# Enhanced Models with achievements and social features
class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    email: str
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    avatar: Optional[str] = None
    credits: int = 0
    leagues_won: int = 0
    total_spent: int = 0
    achievements: List[dict] = []
    total_points: int = 0
    is_online: bool = False
    last_seen: Optional[datetime] = None

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    avatar: Optional[str] = None
    credits: int
    leagues_won: int
    total_spent: int
    created_at: datetime
    achievements: List[dict] = []
    total_points: int = 0
    is_online: bool = False

class Player(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    sport: str = "cricket"
    position: PlayerPosition
    rating: int
    price: int
    image: Optional[str] = None
    stats: Dict[str, Any]
    created_at: datetime = Field(default_factory=datetime.utcnow)

class PlayerCreate(BaseModel):
    name: str
    position: PlayerPosition
    rating: int
    price: int
    image: Optional[str] = None
    stats: Dict[str, Any]

class SquadComposition(BaseModel):
    batsmen: int
    bowlers: int
    all_rounders: int
    wicket_keepers: int

class TournamentParticipant(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    username: str
    budget: int
    current_budget: int
    squad: List[str] = []  # Player IDs
    total_score: int = 0
    is_admin: bool = False
    invite_status: InviteStatus = InviteStatus.PENDING
    is_online: bool = False

class Tournament(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    sport: str = "cricket"
    real_life_tournament: str
    admin_id: str
    participants: List[TournamentParticipant] = []
    max_participants: int
    status: TournamentStatus = TournamentStatus.DRAFT
    budget: int
    squad_composition: SquadComposition
    auction_date: Optional[datetime] = None
    auction_duration: float = 2.0  # hours
    created_at: datetime = Field(default_factory=datetime.utcnow)
    invite_code: Optional[str] = None

class TournamentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    real_life_tournament: str
    max_participants: int
    budget: int
    squad_composition: SquadComposition
    auction_date: Optional[datetime] = None
    auction_duration: float = 2.0

class TournamentJoin(BaseModel):
    invite_code: str

class Auction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tournament_id: str
    player_id: str
    current_bid: int
    highest_bidder_id: Optional[str] = None
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    is_active: bool = True
    min_increment: int = 25000
    winner_id: Optional[str] = None
    final_price: Optional[int] = None

class AuctionCreate(BaseModel):
    tournament_id: str
    player_id: str
    duration_minutes: int = 180

class Bid(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    auction_id: str
    user_id: str
    username: str
    amount: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    is_winning: bool = False

class BidCreate(BaseModel):
    amount: int

class NotificationCreate(BaseModel):
    title: str
    message: str
    type: str = "info"  # info, success, warning, error

class AuctionMessage(BaseModel):
    user_id: str
    username: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

# Default cricket players data (same as before)
CRICKET_PLAYERS = [
    {
        "id": "1", "name": "Virat Kohli", "position": "Batsman", "rating": 95, "price": 850000,
        "stats": {"runs": 12000, "average": 59.07, "centuries": 70, "matches": 254}
    },
    {
        "id": "2", "name": "MS Dhoni", "position": "Wicket Keeper", "rating": 92, "price": 750000,
        "stats": {"runs": 10500, "sixes": 229, "matches": 350, "dismissals": 444}
    },
    {
        "id": "3", "name": "Rohit Sharma", "position": "Batsman", "rating": 91, "price": 680000,
        "stats": {"runs": 9500, "average": 48.96, "doublecenturies": 3, "matches": 243}
    },
    {
        "id": "4", "name": "Jasprit Bumrah", "position": "Bowler", "rating": 94, "price": 720000,
        "stats": {"wickets": 130, "economy": 4.2, "average": 24.5, "matches": 72}
    },
    {
        "id": "5", "name": "KL Rahul", "position": "Wicket Keeper", "rating": 88, "price": 580000,
        "stats": {"runs": 8000, "average": 47.1, "strikerate": 135.2, "matches": 148}
    },
    {
        "id": "6", "name": "Hardik Pandya", "position": "All Rounder", "rating": 90, "price": 650000,
        "stats": {"runs": 4500, "wickets": 85, "sixes": 156, "matches": 125}
    },
    {
        "id": "7", "name": "Rishabh Pant", "position": "Wicket Keeper", "rating": 89, "price": 620000,
        "stats": {"runs": 6800, "average": 43.5, "sixes": 98, "matches": 87}
    },
    {
        "id": "8", "name": "Ravindra Jadeja", "position": "All Rounder", "rating": 88, "price": 590000,
        "stats": {"runs": 5500, "wickets": 220, "catches": 157, "matches": 168}
    },
    {
        "id": "9", "name": "Shikhar Dhawan", "position": "Batsman", "rating": 85, "price": 480000,
        "stats": {"runs": 7200, "average": 45.1, "centuries": 17, "matches": 167}
    },
    {
        "id": "10", "name": "Mohammed Shami", "position": "Bowler", "rating": 87, "price": 520000,
        "stats": {"wickets": 180, "economy": 5.1, "average": 28.5, "matches": 87}
    },
    {
        "id": "11", "name": "AB de Villiers", "position": "Batsman", "rating": 93, "price": 780000,
        "stats": {"runs": 9577, "average": 53.5, "centuries": 25, "strikerate": 101.1}
    },
    {
        "id": "12", "name": "Jos Buttler", "position": "Wicket Keeper", "rating": 90, "price": 640000,
        "stats": {"runs": 4500, "strikerate": 140.2, "sixes": 178, "matches": 162}
    },
    {
        "id": "13", "name": "David Warner", "position": "Batsman", "rating": 89, "price": 610000,
        "stats": {"runs": 5455, "average": 48.8, "centuries": 18, "matches": 112}
    },
    {
        "id": "14", "name": "Kagiso Rabada", "position": "Bowler", "rating": 91, "price": 670000,
        "stats": {"wickets": 252, "economy": 4.3, "average": 22.9, "matches": 57}
    },
    {
        "id": "15", "name": "Rashid Khan", "position": "Bowler", "rating": 92, "price": 700000,
        "stats": {"wickets": 170, "economy": 6.2, "average": 18.4, "matches": 76}
    },
    {
        "id": "16", "name": "Andre Russell", "position": "All Rounder", "rating": 87, "price": 550000,
        "stats": {"runs": 1800, "wickets": 65, "strikerate": 177.9, "sixes": 120}
    },
    {
        "id": "17", "name": "Chris Gayle", "position": "Batsman", "rating": 84, "price": 460000,
        "stats": {"runs": 14562, "sixes": 553, "centuries": 42, "strikerate": 137.5}
    },
    {
        "id": "18", "name": "Trent Boult", "position": "Bowler", "rating": 88, "price": 560000,
        "stats": {"wickets": 311, "economy": 4.9, "average": 27.5, "matches": 93}
    },
    {
        "id": "19", "name": "Ben Stokes", "position": "All Rounder", "rating": 90, "price": 650000,
        "stats": {"runs": 2919, "wickets": 42, "average": 35.4, "matches": 105}
    },
    {
        "id": "20", "name": "Sunil Narine", "position": "All Rounder", "rating": 85, "price": 490000,
        "stats": {"runs": 1025, "wickets": 152, "economy": 6.7, "strikerate": 168.3}
    }
]

# Utility functions (same as before)
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm="HS256")
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        
        user = await db.users.find_one({"id": user_id})
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        
        # Update last seen and online status
        await db.users.update_one(
            {"id": user_id},
            {"$set": {"last_seen": datetime.utcnow(), "is_online": True}}
        )
        
        return User(**user)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

def generate_invite_code() -> str:
    import random
    import string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# WebSocket endpoint for real-time features
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            message = eval(data)  # In production, use json.loads with proper validation
            
            if message.get("type") == "join_auction":
                auction_id = message.get("auction_id")
                username = message.get("username", "Anonymous")
                await manager.join_auction(user_id, auction_id, username)
                
            elif message.get("type") == "leave_auction":
                username = message.get("username", "Anonymous")
                await manager.leave_auction(user_id, username)
                
            elif message.get("type") == "ping":
                await manager.send_personal_message({"type": "pong"}, user_id)
                
    except WebSocketDisconnect:
        manager.disconnect(user_id)

# Initialize database with cricket players and create indexes for performance
async def init_db():
    # Check if players collection is empty
    player_count = await db.players.count_documents({})
    if player_count == 0:
        # Insert default cricket players
        players = [Player(**player_data) for player_data in CRICKET_PLAYERS]
        player_dicts = [player.dict() for player in players]
        await db.players.insert_many(player_dicts)
        logger.info(f"Inserted {len(players)} cricket players into database")

    # Create database indexes for performance
    try:
        # Users collection indexes
        await db.users.create_index([("email", 1)], unique=True)
        await db.users.create_index([("username", 1)])
        await db.users.create_index([("is_online", 1)])
        await db.users.create_index([("created_at", -1)])

        # Players collection indexes
        await db.players.create_index([("name", 1)])
        await db.players.create_index([("position", 1)])
        await db.players.create_index([("rating", -1)])
        await db.players.create_index([("price", 1)])
        await db.players.create_index([("sport", 1)])
        
        # Tournaments collection indexes
        await db.tournaments.create_index([("admin_id", 1)])
        await db.tournaments.create_index([("status", 1)])
        await db.tournaments.create_index([("created_at", -1)])
        await db.tournaments.create_index([("invite_code", 1)], unique=True, sparse=True)
        await db.tournaments.create_index([("name", "text"), ("real_life_tournament", "text")])
        
        # Auctions collection indexes
        await db.auctions.create_index([("tournament_id", 1)])
        await db.auctions.create_index([("player_id", 1)])
        await db.auctions.create_index([("is_active", 1)])
        await db.auctions.create_index([("highest_bidder_id", 1)])
        await db.auctions.create_index([("end_time", 1)])
        await db.auctions.create_index([("start_time", -1)])
        
        # Bids collection indexes
        await db.bids.create_index([("auction_id", 1)])
        await db.bids.create_index([("user_id", 1)])
        await db.bids.create_index([("timestamp", -1)])
        await db.bids.create_index([("is_winning", 1)])
        await db.bids.create_index([("amount", -1)])
        
        logger.info("Database indexes created successfully for optimal performance")
        
    except Exception as e:
        logger.error(f"Error creating database indexes: {e}")

# Routes (keeping existing ones and adding new ones)
@api_router.get("/")
async def root():
    return {
        "message": "SportX Cricket Auction API", 
        "version": "1.0.0",
        "features": ["Real-time bidding", "WebSocket support", "Achievements", "Social features"],
        "online_users": manager.get_online_users_count()
    }

# Enhanced Authentication routes
@api_router.post("/auth/register", response_model=UserResponse)
async def register(user_data: UserCreate):
    # Check if user already exists
    existing_user = await db.users.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create new user
    hashed_password = hash_password(user_data.password)
    user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hashed_password,
        is_online=True
    )
    
    await db.users.insert_one(user.dict())
    
    # Check for first-time achievements
    await achievement_manager.check_achievements(user.id, "register", {}, db)
    
    return UserResponse(**user.dict())

@api_router.post("/auth/login")
async def login(user_data: UserLogin):
    user = await db.users.find_one({"email": user_data.email})
    if not user or not verify_password(user_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Update online status
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"is_online": True, "last_seen": datetime.utcnow()}}
    )
    
    access_token = create_access_token(data={"sub": user["id"]})
    return {"access_token": access_token, "token_type": "bearer", "user": UserResponse(**user)}

@api_router.get("/auth/profile", response_model=UserResponse)
async def get_profile(current_user: User = Depends(get_current_user)):
    return UserResponse(**current_user.dict())

@api_router.post("/auth/logout")
async def logout(current_user: User = Depends(get_current_user)):
    # Update offline status
    await db.users.update_one(
        {"id": current_user.id},
        {"$set": {"is_online": False, "last_seen": datetime.utcnow()}}
    )
    return {"message": "Logged out successfully"}

# Player routes (same as before)
@api_router.get("/players", response_model=List[Player])
async def get_players(position: Optional[str] = None, search: Optional[str] = None):
    query = {}
    if position:
        query["position"] = position
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"position": {"$regex": search, "$options": "i"}}
        ]
    
    players = await db.players.find(query).to_list(100)
    return [Player(**player) for player in players]

@api_router.get("/players/{player_id}", response_model=Player)
async def get_player(player_id: str):
    player = await db.players.find_one({"id": player_id})
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return Player(**player)

@api_router.post("/players", response_model=Player)
async def create_player(player_data: PlayerCreate, current_user: User = Depends(get_current_user)):
    player = Player(**player_data.dict())
    await db.players.insert_one(player.dict())
    return player

# Enhanced Tournament routes
@api_router.get("/tournaments", response_model=List[Tournament])
async def get_tournaments(status: Optional[str] = None, search: Optional[str] = None):
    query = {}
    if status:
        query["status"] = status
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"real_life_tournament": {"$regex": search, "$options": "i"}}
        ]
    
    tournaments = await db.tournaments.find(query).to_list(100)
    return [Tournament(**tournament) for tournament in tournaments]

@api_router.get("/tournaments/{tournament_id}", response_model=Tournament)
async def get_tournament(tournament_id: str):
    tournament = await db.tournaments.find_one({"id": tournament_id})
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return Tournament(**tournament)

@api_router.post("/tournaments", response_model=Tournament)
async def create_tournament(tournament_data: TournamentCreate, current_user: User = Depends(get_current_user)):
    tournament = Tournament(
        **tournament_data.dict(),
        admin_id=current_user.id,
        invite_code=generate_invite_code()
    )
    
    # Add creator as first participant
    admin_participant = TournamentParticipant(
        user_id=current_user.id,
        username=current_user.username,
        budget=tournament.budget,
        current_budget=tournament.budget,
        is_admin=True,
        invite_status=InviteStatus.ACCEPTED,
        is_online=current_user.is_online
    )
    tournament.participants.append(admin_participant)
    tournament.status = TournamentStatus.SETUP
    
    await db.tournaments.insert_one(tournament.dict())
    
    # Check achievements
    await achievement_manager.check_achievements(current_user.id, "create_tournament", {}, db)
    
    return tournament

@api_router.post("/tournaments/{tournament_id}/join", response_model=Tournament)
async def join_tournament(tournament_id: str, join_data: TournamentJoin, current_user: User = Depends(get_current_user)):
    tournament = await db.tournaments.find_one({"id": tournament_id})
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    tournament_obj = Tournament(**tournament)
    
    # Check invite code
    if tournament_obj.invite_code != join_data.invite_code:
        raise HTTPException(status_code=400, detail="Invalid invite code")
    
    # Check if already joined
    for participant in tournament_obj.participants:
        if participant.user_id == current_user.id:
            raise HTTPException(status_code=400, detail="Already joined tournament")
    
    # Check if tournament is full
    if len(tournament_obj.participants) >= tournament_obj.max_participants:
        raise HTTPException(status_code=400, detail="Tournament is full")
    
    # Add participant
    participant = TournamentParticipant(
        user_id=current_user.id,
        username=current_user.username,
        budget=tournament_obj.budget,
        current_budget=tournament_obj.budget,
        invite_status=InviteStatus.ACCEPTED,
        is_online=current_user.is_online
    )
    tournament_obj.participants.append(participant)
    
    await db.tournaments.update_one(
        {"id": tournament_id},
        {"$set": {"participants": [p.dict() for p in tournament_obj.participants]}}
    )

    return tournament_obj


class PlayerScoreUpdate(BaseModel):
    player_id: str
    stats: PerformanceStats


@api_router.post("/tournaments/{tournament_id}/score")
async def update_player_score(tournament_id: str, update: PlayerScoreUpdate):
    """Update a player's score and apply it to the owning participant."""
    tournament = await db.tournaments.find_one({"id": tournament_id})
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    tournament_obj = Tournament(**tournament)
    points = calculate_points(update.stats)
    updated = False

    for participant in tournament_obj.participants:
        if update.player_id in participant.squad:
            participant.total_score += points
            updated = True

    if updated:
        await db.tournaments.update_one(
            {"id": tournament_id},
            {"$set": {"participants": [p.dict() for p in tournament_obj.participants]}}
        )

    return {"player_id": update.player_id, "points": points}


@api_router.get("/tournaments/{tournament_id}/leaderboard")
async def get_leaderboard(tournament_id: str):
    """Return tournament participants ordered by score."""
    tournament = await db.tournaments.find_one({"id": tournament_id})
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    tournament_obj = Tournament(**tournament)
    participants = sorted(
        tournament_obj.participants,
        key=lambda p: p.total_score,
        reverse=True,
    )
    return [
        {"user_id": p.user_id, "username": p.username, "score": p.total_score}
        for p in participants
    ]

# Enhanced Auction routes with real-time features
@api_router.get("/auctions", response_model=List[Auction])
async def get_auctions(tournament_id: Optional[str] = None, is_active: Optional[bool] = None):
    query = {}
    if tournament_id:
        query["tournament_id"] = tournament_id
    if is_active is not None:
        query["is_active"] = is_active
    
    auctions = await db.auctions.find(query).to_list(100)
    return [Auction(**auction) for auction in auctions]

@api_router.get("/auctions/{auction_id}", response_model=Auction)
async def get_auction(auction_id: str):
    auction = await db.auctions.find_one({"id": auction_id})
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")
    return Auction(**auction)

@api_router.post("/auctions", response_model=Auction)
async def create_auction(auction_data: AuctionCreate, current_user: User = Depends(get_current_user)):
    # Verify tournament exists and user is admin
    tournament = await db.tournaments.find_one({"id": auction_data.tournament_id})
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    tournament_obj = Tournament(**tournament)
    if tournament_obj.admin_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only tournament admin can create auctions")
    
    # Get player
    player = await db.players.find_one({"id": auction_data.player_id})
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    
    auction = Auction(
        tournament_id=auction_data.tournament_id,
        player_id=auction_data.player_id,
        current_bid=player["price"],
        end_time=datetime.utcnow() + timedelta(minutes=auction_data.duration_minutes)
    )
    
    await db.auctions.insert_one(auction.dict())
    
    # Start auction timer
    await auction_timer.start_auction_timer(auction.id, auction_data.duration_minutes * 60, db)
    
    return auction

@api_router.post("/auctions/{auction_id}/bid", response_model=Bid)
async def place_bid(auction_id: str, bid_data: BidCreate, current_user: User = Depends(get_current_user)):
    auction = await db.auctions.find_one({"id": auction_id})
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")
    
    auction_obj = Auction(**auction)
    
    # Check if auction is active
    if not auction_obj.is_active:
        raise HTTPException(status_code=400, detail="Auction is not active")
    
    # Check if auction has ended
    if auction_obj.end_time and datetime.utcnow() > auction_obj.end_time:
        raise HTTPException(status_code=400, detail="Auction has ended")
    
    # Check minimum bid
    min_bid = auction_obj.current_bid + auction_obj.min_increment
    if bid_data.amount < min_bid:
        raise HTTPException(status_code=400, detail=f"Minimum bid is ${min_bid}")
    
    # Create bid
    bid = Bid(
        auction_id=auction_id,
        user_id=current_user.id,
        username=current_user.username,
        amount=bid_data.amount,
        is_winning=True
    )
    
    # Update previous bids to not winning
    await db.bids.update_many(
        {"auction_id": auction_id},
        {"$set": {"is_winning": False}}
    )
    
    # Insert new bid
    await db.bids.insert_one(bid.dict())
    
    # Update auction
    await db.auctions.update_one(
        {"id": auction_id},
        {"$set": {
            "current_bid": bid_data.amount,
            "highest_bidder_id": current_user.id
        }}
    )
    
    # Extend timer if bid placed in final 30 seconds
    time_remaining = auction_timer.get_time_remaining(auction_id)
    if time_remaining and time_remaining <= 30:
        await auction_timer.extend_auction_timer(auction_id, 30)
    
    # Broadcast bid update via WebSocket
    await manager.broadcast_bid_update(auction_id, bid.dict())
    
    # Check achievements
    await achievement_manager.check_achievements(
        current_user.id, 
        "place_bid", 
        {"amount": bid_data.amount, "auction_id": auction_id}, 
        db
    )
    
    return bid

@api_router.get("/auctions/{auction_id}/bids", response_model=List[Bid])
async def get_auction_bids(auction_id: str):
    bids = await db.bids.find({"auction_id": auction_id}).sort("timestamp", -1).to_list(100)
    return [Bid(**bid) for bid in bids]

# New Achievement routes
@api_router.get("/achievements", response_model=List[Achievement])
async def get_user_achievements(current_user: User = Depends(get_current_user)):
    achievements = await achievement_manager.get_user_achievements(current_user.id, db)
    return achievements

@api_router.get("/achievements/progress")
async def get_achievement_progress(current_user: User = Depends(get_current_user)):
    progress = await achievement_manager.get_achievement_progress(current_user.id, db)
    return progress

# Statistics routes
@api_router.get("/stats/live")
async def get_live_stats():
    total_users = await db.users.count_documents({})
    online_users = await db.users.count_documents({"is_online": True})
    active_auctions = await db.auctions.count_documents({"is_active": True})
    total_tournaments = await db.tournaments.count_documents({})
    
    return {
        "total_users": total_users,
        "online_users": online_users,
        "active_auctions": active_auctions,
        "total_tournaments": total_tournaments,
        "websocket_connections": manager.get_online_users_count()
    }

# Cricket data routes
@api_router.post("/cricket/populate-players")
async def populate_cricket_players():
    """Populate database with real cricket players from API"""
    try:
        from cricket_service import cricket_service
        
        # Get list of famous players
        player_names = await cricket_service.search_famous_cricket_players()
        populated_players = []
        failed_players = []
        
        for player_name in player_names:
            try:
                # Get player data from API
                cricket_player = await cricket_service.get_player_by_name(player_name)
                
                if cricket_player:
                    # Convert to our Player model format
                    player_data = {
                        "id": str(uuid.uuid4()),
                        "name": cricket_player.name,
                        "sport": "cricket",
                        "position": cricket_player.role if isinstance(cricket_player.role, str) else (cricket_player.role.value if cricket_player.role else "Batsman"),
                        "rating": min(max(int((cricket_player.base_price or 100000) / 25000), 1), 100),
                        "price": int(cricket_player.base_price or 100000),
                        "image": None,  # Will be populated separately
                        "stats": {
                            "matches": sum([cs.batting.matches or 0 for cs in cricket_player.career_summaries if cs.batting]),
                            "runs": sum([cs.batting.runs or 0 for cs in cricket_player.career_summaries if cs.batting]),
                            "average": max([cs.batting.average or 0 for cs in cricket_player.career_summaries if cs.batting] + [0]),
                            "strike_rate": max([cs.batting.strike_rate or 0 for cs in cricket_player.career_summaries if cs.batting] + [0]),
                            "centuries": sum([cs.batting.centuries or 0 for cs in cricket_player.career_summaries if cs.batting]),
                            "wickets": sum([cs.bowling.wickets or 0 for cs in cricket_player.career_summaries if cs.bowling]),
                            "economy": min([cs.bowling.economy or 10 for cs in cricket_player.career_summaries if cs.bowling] + [10]),
                            "base_price": cricket_player.base_price or 100000
                        }
                    }
                    
                    # Save to database
                    await db.players.replace_one(
                        {"name": player_data["name"]},
                        player_data,
                        upsert=True
                    )
                    
                    populated_players.append(player_data["name"])
                    logger.info(f"Populated player: {player_data['name']}")
                    
                else:
                    failed_players.append(player_name)
                    
            except Exception as e:
                logger.error(f"Failed to populate player {player_name}: {str(e)}")
                failed_players.append(player_name)
        
        return {
            "message": f"Successfully populated {len(populated_players)} players",
            "populated_players": populated_players,
            "failed_players": failed_players,
            "total_attempted": len(player_names)
        }
        
    except Exception as e:
        logger.error(f"Failed to populate cricket players: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to populate players: {str(e)}")

@api_router.get("/cricket/player/{player_name}")
async def get_cricket_player_details(player_name: str):
    """Get detailed cricket player information"""
    try:
        from cricket_service import cricket_service
        
        cricket_player = await cricket_service.get_player_by_name(player_name)
        
        if not cricket_player:
            raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found in cricket database")
        
        return {
            "success": True,
            "data": cricket_player.dict(),
            "message": f"Player data retrieved for {player_name}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cricket player {player_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get player data: {str(e)}")

@api_router.get("/cricket/live-matches")
async def get_cricket_live_matches():
    """Get current live cricket matches"""
    try:
        from cricket_service import cricket_service
        
        matches = await cricket_service.get_live_matches()
        
        return {
            "success": True,
            "data": matches,
            "message": f"Retrieved {len(matches)} live matches"
        }
        
    except Exception as e:
        logger.error(f"Failed to get live matches: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get live matches: {str(e)}")

@api_router.get("/cricket/scores")
async def get_cricket_scores():
    """Get cricket scores and match information"""
    try:
        from cricket_service import cricket_service
        
        scores = await cricket_service.get_cricket_scores()
        
        return {
            "success": True,
            "data": scores,
            "message": "Cricket scores retrieved successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to get cricket scores: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get cricket scores: {str(e)}")

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    await init_db()
    logger.info("SportX Cricket Auction API started with WebSocket support")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
