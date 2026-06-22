"""
Chess Trainer - Learn from your mistakes
Analyzes chess.com and Lichess game history to provide personalized training
"""

import json
import requests
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import chess
import chess.pgn
from io import StringIO


class TrainingMode(Enum):
    """Different training modes available"""
    OPENING = "opening"
    TACTICS = "tactics"
    ENDGAME = "endgame"
    MIDDLEGAME = "middlegame"
    WEAKNESSES = "weaknesses"


@dataclass
class GameAnalysis:
    """Stores analysis of a single game"""
    game_id: str
    result: str
    opening_name: str
    opening_eco: str
    mistakes: List[Dict]
    blunders: List[Dict]
    inaccuracies: List[Dict]
    player_color: str
    opponent_rating: int
    player_rating: int
    game_duration: int


@dataclass
class OpeningStats:
    """Statistics for a specific opening"""
    opening_name: str
    eco_code: str
    games_played: int
    win_rate: float
    loss_rate: float
    draw_rate: float
    average_rating: float
    common_mistakes: List[str]


class ChessComAPI:
    """Interact with Chess.com API"""
    
    BASE_URL = "https://api.chess.com/pub"
    
    def get_player_games(self, username: str, year_month: Optional[str] = None) -> List[Dict]:
        """
        Fetch games for a player
        year_month format: "2024/01"
        """
        try:
            if year_month:
                url = f"{self.BASE_URL}/player/{username}/games/{year_month}"
            else:
                url = f"{self.BASE_URL}/player/{username}/games/archives"
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                archives = response.json().get('archives', [])
                
                all_games = []
                for archive_url in archives[-3:]:  # Last 3 months
                    archive_response = requests.get(archive_url, timeout=10)
                    archive_response.raise_for_status()
                    all_games.extend(archive_response.json().get('games', []))
                return all_games
            
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json().get('games', [])
        
        except requests.exceptions.RequestException as e:
            print(f"Error fetching games: {e}")
            return []
    
    def get_player_profile(self, username: str) -> Dict:
        """Get player profile information"""
        try:
            url = f"{self.BASE_URL}/player/{username}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching profile: {e}")
            return {}


class LichessAPI:
    """Interact with Lichess API"""
    
    BASE_URL = "https://lichess.org/api"
    
    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.headers = {}
        if token:
            self.headers['Authorization'] = f'Bearer {token}'
    
    def get_player_games(self, username: str, max_games: int = 100) -> List[Dict]:
        """Fetch recent games for a player"""
        try:
            url = f"{self.BASE_URL}/games/user/{username}"
            params = {'max': max_games, 'pgnInJson': True}
            
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            games = []
            for line in response.text.strip().split('\n'):
                if line:
                    games.append(json.loads(line))
            return games
        
        except requests.exceptions.RequestException as e:
            print(f"Error fetching Lichess games: {e}")
            return []
    
    def get_player_profile(self, username: str) -> Dict:
        """Get player profile information"""
        try:
            url = f"{self.BASE_URL}/user/{username}"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching profile: {e}")
            return {}


class GameAnalyzer:
    """Analyzes chess games for mistakes and patterns"""
    
    OPENING_TRANSITIONS = {
        "A00": "Irregular Openings",
        "A01-A03": "Larsen's Opening",
        "A04-A09": "Bird's Opening",
        "B00": "Irregular Defenses",
        "B01": "Scandinavian Defense",
        "B02-B05": "Alekhine's Defense",
        "B06": "Robatsch/Modern Defense",
        "B07-B09": "Pirc Defense",
        "B10-B19": "Caro-Kann Defense",
        "B20-B99": "Sicilian Defense",
        "C00-C19": "French Defense",
        "C20-C99": "Italian Game & Others",
        "D00-D05": "Queen's Gambit Declined",
        "D06-D69": "Queen's Gambit Accepted",
        "D70-D99": "Neo-Meran/Other QGA",
        "E00-E59": "Indian Defenses",
        "E60-E99": "King's Indian Defense"
    }
    
    def analyze_game(self, pgn_string: str, player_username: str, 
                    source: str = "chess.com") -> Optional[GameAnalysis]:
        """
        Analyze a single game from PGN
        """
        try:
            pgn_io = StringIO(pgn_string)
            game = chess.pgn.read_game(pgn_io)
            
            if not game:
                return None
            
            # Extract metadata
            white = game.headers.get('White', 'Unknown')
            black = game.headers.get('Black', 'Unknown')
            result = game.headers.get('Result', '*')
            opening_name = game.headers.get('Opening', 'Unknown')
            opening_eco = game.headers.get('ECO', 'A00')
            
            # Determine player color
            player_color = 'white' if white.lower() == player_username.lower() else 'black'
            
            # Analyze moves for mistakes
            mistakes, blunders, inaccuracies = self._detect_mistakes(game)
            
            return GameAnalysis(
                game_id=game.headers.get('Site', 'unknown').split('/')[-1],
                result=result,
                opening_name=opening_name,
                opening_eco=opening_eco,
                mistakes=mistakes,
                blunders=blunders,
                inaccuracies=inaccuracies,
                player_color=player_color,
                opponent_rating=int(black.split('(')[-1].rstrip(')')) if '(' in black else 1600,
                player_rating=int(white.split('(')[-1].rstrip(')')) if '(' in white else 1600,
                game_duration=(game.end_time - game.start_time).total_seconds() if hasattr(game, 'end_time') else 0
            )
        
        except Exception as e:
            print(f"Error analyzing game: {e}")
            return None
    
    def _detect_mistakes(self, game: chess.pgn.Game) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """
        Detect mistakes, blunders, and inaccuracies in a game
        This is simplified - in production use Stockfish or similar engine
        """
        mistakes = []
        blunders = []
        inaccuracies = []
        
        # Simplified detection based on move quality
        # In production, integrate with chess engine for proper evaluation
        board = game.board()
        move_number = 1
        
        for move in game.mainline_moves():
            # Simple heuristic: detect illegal-looking captures or sacrifices
            if board.is_capture(move):
                captured_piece = board.piece_at(move.to_square)
                moving_piece = board.piece_at(move.from_square)
                
                if captured_piece and moving_piece:
                    if chess.piece_value(captured_piece.piece_type) < chess.piece_value(moving_piece.piece_type):
                        inaccuracies.append({
                            'move_number': move_number,
                            'move': move.uci(),
                            'type': 'questionable_capture'
                        })
            
            board.push(move)
            move_number += 1
        
        return mistakes, blunders, inaccuracies


class TrainingSession:
    """Manages a training session"""
    
    def __init__(self, mode: TrainingMode, opening_eco: Optional[str] = None):
        self.mode = mode
        self.opening_eco = opening_eco
        self.board = chess.Board()
        self.moves_played = []
        self.score = 0
        self.total_moves = 0
    
    def start_position(self, fen: Optional[str] = None):
        """Start training from a specific position"""
        if fen:
            self.board.set_fen(fen)
        else:
            self.board.reset()
        self.moves_played = []
    
    def validate_move(self, move_uci: str) -> Tuple[bool, str]:
        """
        Validate a move in the current position
        Returns (is_valid, message)
        """
        try:
            move = chess.Move.from_uci(move_uci)
            if move in self.board.legal_moves:
                self.board.push(move)
                self.moves_played.append(move_uci)
                self.total_moves += 1
                return True, "Valid move"
            else:
                return False, "Move is not legal in this position"
        except ValueError:
            return False, "Invalid move format"
    
    def get_legal_moves(self) -> List[str]:
        """Get all legal moves in current position"""
        return [move.uci() for move in self.board.legal_moves]
    
    def get_board_fen(self) -> str:
        """Get current board FEN"""
        return self.board.fen()
    
    def get_board_display(self) -> str:
        """Get ASCII representation of board"""
        return str(self.board)
    
    def is_game_over(self) -> bool:
        """Check if the game is over"""
        return self.board.is_game_over()
    
    def get_result(self) -> str:
        """Get game result"""
        if self.board.is_checkmate():
            return "Checkmate"
        elif self.board.is_stalemate():
            return "Stalemate"
        elif self.board.is_insufficient_material():
            return "Draw - Insufficient Material"
        elif self.board.is_fivefold_repetition():
            return "Draw - Repetition"
        else:
            return "Game continues"


class ChessTrainer:
    """Main chess training coordinator"""
    
    def __init__(self, source: str = "chess.com", username: str = "", lichess_token: Optional[str] = None):
        """
        Initialize trainer
        source: "chess.com" or "lichess"
        """
        self.source = source.lower()
        self.username = username
        self.game_analyses: List[GameAnalysis] = []
        
        if self.source == "chess.com":
            self.api = ChessComAPI()
        elif self.source == "lichess":
            self.api = LichessAPI(token=lichess_token)
        else:
            raise ValueError(f"Unknown source: {source}")
        
        self.analyzer = GameAnalyzer()
    
    def load_game_history(self, username: Optional[str] = None, max_games: int = 50) -> int:
        """
        Load and analyze game history
        Returns number of games loaded
        """
        username = username or self.username
        
        print(f"Loading games from {self.source} for {username}...")
        games = self.api.get_player_games(username)[:max_games]
        
        print(f"Analyzing {len(games)} games...")
        for game_data in games:
            if self.source == "chess.com":
                pgn = game_data.get('pgn', '')
            else:  # lichess
                pgn = game_data.get('pgn', '')
            
            if pgn:
                analysis = self.analyzer.analyze_game(pgn, username, self.source)
                if analysis:
                    self.game_analyses.append(analysis)
        
        print(f"Successfully analyzed {len(self.game_analyses)} games")
        return len(self.game_analyses)
    
    def get_opening_statistics(self) -> Dict[str, OpeningStats]:
        """Analyze performance in different openings"""
        opening_stats = {}
        
        for analysis in self.game_analyses:
            eco = analysis.opening_eco
            
            if eco not in opening_stats:
                opening_stats[eco] = {
                    'name': analysis.opening_name,
                    'games': 0,
                    'wins': 0,
                    'losses': 0,
                    'draws': 0,
                    'total_rating': 0,
                    'mistakes': []
                }
            
            stats = opening_stats[eco]
            stats['games'] += 1
            stats['total_rating'] += analysis.opponent_rating
            
            # Parse result
            if '1-0' in analysis.result and analysis.player_color == 'white':
                stats['wins'] += 1
            elif '0-1' in analysis.result and analysis.player_color == 'black':
                stats['wins'] += 1
            elif '1/2' in analysis.result:
                stats['draws'] += 1
            else:
                stats['losses'] += 1
            
            stats['mistakes'].extend([m['move'] for m in analysis.mistakes])
        
        # Calculate win rates
        result = {}
        for eco, stats in opening_stats.items():
            games = max(1, stats['games'])
            result[eco] = OpeningStats(
                opening_name=stats['name'],
                eco_code=eco,
                games_played=stats['games'],
                win_rate=stats['wins'] / games,
                loss_rate=stats['losses'] / games,
                draw_rate=stats['draws'] / games,
                average_rating=stats['total_rating'] / games,
                common_mistakes=list(set(stats['mistakes']))[:5]
            )
        
        return result
    
    def identify_weak_openings(self) -> List[Tuple[str, float]]:
        """
        Identify openings with lowest win rate (good for focused training)
        Returns list of (opening_eco, win_rate) sorted by win rate
        """
        opening_stats = self.get_opening_statistics()
        
        weak_openings = [
            (eco, stats.win_rate) 
            for eco, stats in opening_stats.items() 
            if stats.games_played >= 3  # Only openings played at least 3 times
        ]
        
        return sorted(weak_openings, key=lambda x: x[1])
    
    def create_training_session(self, mode: TrainingMode, 
                               opening_eco: Optional[str] = None) -> TrainingSession:
        """Create a new training session"""
        return TrainingSession(mode, opening_eco)
    
    def print_game_summary(self):
        """Print summary of analyzed games"""
        if not self.game_analyses:
            print("No games loaded. Run load_game_history() first.")
            return
        
        print("\n" + "="*60)
        print("GAME ANALYSIS SUMMARY")
        print("="*60)
        print(f"Total games analyzed: {len(self.game_analyses)}\n")
        
        opening_stats = self.get_opening_statistics()
        print("Opening Statistics (sorted by games played):")
        print("-"*60)
        
        for eco in sorted(opening_stats.keys(), 
                         key=lambda x: opening_stats[x].games_played, 
                         reverse=True):
            stats = opening_stats[eco]
            if stats.games_played >= 2:
                print(f"{stats.opening_name} ({eco})")
                print(f"  Games: {stats.games_played} | Win Rate: {stats.win_rate*100:.1f}% | Avg Opp Rating: {stats.average_rating:.0f}")
                if stats.common_mistakes:
                    print(f"  Common mistakes: {', '.join(stats.common_mistakes[:3])}")
                print()
        
        weak_openings = self.identify_weak_openings()
        if weak_openings:
            print("Weak Openings (recommended for training):")
            print("-"*60)
            for eco, win_rate in weak_openings[:5]:
                opening_name = opening_stats[eco].opening_name
                print(f"  • {opening_name} ({eco}): {win_rate*100:.1f}% win rate")
            print()
        
        print("="*60 + "\n")


if __name__ == "__main__":
    # Example usage
    print("Chess Trainer - Learn from your games!")
    print()
    
    # Initialize trainer for Chess.com
    trainer = ChessTrainer(source="chess.com", username="example_username")
    
    # Load games
    # trainer.load_game_history(max_games=50)
    # trainer.print_game_summary()
    
    # Create a training session
    # session = trainer.create_training_session(TrainingMode.OPENING, opening_eco="B20")
    # session.start_position()
    # print(session.get_board_display())
