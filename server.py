from flask import Flask, request, jsonify, render_template
import random
import google.generativeai as genai
import itertools
import json
import threading
import queue
import os

# --- Gemini API Setup ---
# IMPORTANT: Set your GOOGLE_API_KEY as an environment variable
# For example: export GOOGLE_API_KEY="YOUR_API_KEY"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash') # Updated model
else:
    print("Warning: GOOGLE_API_KEY is not set. Gemini player will be disabled.")
    model = None

# --- Core Game Logic (from poker_gui.py, adapted for web) ---

SUITS = ['♠', '♥', '♦', '♣']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
RANK_VALUES = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}

class Card:
    def __init__(self, suit, rank):
        self.suit = suit
        self.rank = rank
        self.value = RANK_VALUES[rank]

    def to_dict(self):
        return {"suit": self.suit, "rank": self.rank}

class Deck:
    def __init__(self):
        self.cards = [Card(s, r) for s in SUITS for r in RANKS]
        self.shuffle()

    def shuffle(self):
        random.shuffle(self.cards)

    def deal(self):
        return self.cards.pop() if self.cards else None

class Player:
    def __init__(self, name, chips=1000, is_cpu=False, is_gemini=False):
        self.name = name
        self.hand = []
        self.chips = chips
        self.bet = 0
        self.has_acted = False
        self.is_folded = False
        self.is_all_in = False
        self.is_cpu = is_cpu
        self.is_gemini = is_gemini
        self.show_hand = not is_cpu and not is_gemini

    def to_dict(self):
        return {
            "name": self.name,
            "hand": [c.to_dict() for c in self.hand] if self.show_hand else [],
            "chips": self.chips,
            "bet": self.bet,
            "has_acted": self.has_acted,
            "is_folded": self.is_folded,
            "is_all_in": self.is_all_in,
            "is_cpu": self.is_cpu,
            "is_gemini": self.is_gemini,
            "show_hand": self.show_hand
        }

class PokerGame:
    def __init__(self, human_player_name, cpu_players=0, gemini_players=0):
        self.players = []
        self.deck = Deck()
        self.community_cards = []
        self.pot = 0
        self.current_bet = 0
        self.current_player_index = 0
        self.game_stage = "pre-flop"
        self.game_in_progress = False
        self.small_blind_index = -1
        self.big_blind_index = -1
        self.small_blind_amount = 10
        self.big_blind_amount = 20
        self.log_messages = []
        self.action_lock = threading.Lock()
        self.human_action_needed = False

        self.add_player(human_player_name)
        for i in range(cpu_players):
            self.add_player(f"CPU {i+1}", is_cpu=True)
        if model:
            for i in range(gemini_players):
                self.add_player(f"Gemini {i+1}", is_gemini=True)

    def add_player(self, name, is_cpu=False, is_gemini=False):
        self.players.append(Player(name, is_cpu=is_cpu, is_gemini=is_gemini))

    def log(self, message):
        print(message) # For server console
        self.log_messages.append(message)

    def get_state(self):
        return {
            "players": [p.to_dict() for p in self.players],
            "community_cards": [c.to_dict() for c in self.community_cards],
            "pot": self.pot,
            "current_bet": self.current_bet,
            "current_player_index": self.current_player_index,
            "game_stage": self.game_stage,
            "game_in_progress": self.game_in_progress,
            "log": self.log_messages[-10:], # Return last 10 messages
            "human_action_needed": self.human_action_needed
        }

    def start_game_thread(self):
        game_thread = threading.Thread(target=self.start_game, daemon=True)
        game_thread.start()

    def start_game(self):
        if len(self.players) < 2:
            self.log("プレイヤーが2人未満のため、ゲームを開始できません。")
            return
        self.game_in_progress = True
        self.small_blind_index = (self.small_blind_index + 1) % len(self.players)
        self.start_round()

    def start_round(self):
        with self.action_lock:
            self.game_in_progress = True
            self.deck = Deck()
            self.community_cards = []
            self.pot = 0
            self.current_bet = 0
            self.game_stage = "pre-flop"
            self.log_messages.clear()

            self.players = [p for p in self.players if p.chips > 0]
            if len(self.players) < 2:
                self.log("プレイ可能なプレイヤーが2人未満になりました。ゲームを終了します。")
                self.game_in_progress = False
                return

            for player in self.players:
                player.hand = [self.deck.deal(), self.deck.deal()]
                player.bet = 0
                player.has_acted = False
                player.is_folded = False
                player.is_all_in = False
                player.show_hand = not player.is_cpu and not player.is_gemini

            self.small_blind_index = (self.small_blind_index + 1) % len(self.players)
            self.big_blind_index = (self.small_blind_index + 1) % len(self.players)

            sb_player = self.players[self.small_blind_index]
            bb_player = self.players[self.big_blind_index]
            
            self.log(f"{sb_player.name}がスモールブラインド {self.small_blind_amount} をベット。")
            sb_player.bet = min(self.small_blind_amount, sb_player.chips)
            sb_player.chips -= sb_player.bet
            if sb_player.chips == 0: sb_player.is_all_in = True

            self.log(f"{bb_player.name}がビッグブラインド {self.big_blind_amount} をベット。")
            bb_player.bet = min(self.big_blind_amount, bb_player.chips)
            bb_player.chips -= bb_player.bet
            if bb_player.chips == 0: bb_player.is_all_in = True
            
            self.pot += sb_player.bet + bb_player.bet
            self.current_bet = self.big_blind_amount
            self.current_player_index = (self.big_blind_index + 1) % len(self.players)
        
        self.process_betting_round()

    def process_betting_round(self):
        if self.game_stage != "pre-flop":
            with self.action_lock:
                self.current_player_index = (self.small_blind_index) % len(self.players)
                while self.players[self.current_player_index].is_folded or self.players[self.current_player_index].is_all_in:
                    self.current_player_index = (self.current_player_index + 1) % len(self.players)

                self.current_bet = 0
                for p in self.players:
                    p.bet = 0 # Bets are collected at end of round
                    if not p.is_folded and not p.is_all_in:
                        p.has_acted = False
        
        self.process_turn()

    def process_turn(self):
        while self.game_in_progress:
            player_to_act = None
            is_human = False

            with self.action_lock:
                active_players = [p for p in self.players if not p.is_folded]
                if len(active_players) <= 1:
                    self.end_round()
                    return

                active_not_allin = [p for p in active_players if not p.is_all_in]
                acted_players = [p for p in active_not_allin if p.has_acted]
                bets = {p.bet for p in active_not_allin}

                if len(acted_players) == len(active_not_allin) and len(bets) <= 1:
                    self.end_betting_round()
                    return

                current_player = self.players[self.current_player_index]
                if current_player.is_folded or current_player.is_all_in:
                    self.current_player_index = (self.current_player_index + 1) % len(self.players)
                    continue

                player_to_act = current_player
                is_human = not player_to_act.is_cpu and not player_to_act.is_gemini

                if is_human:
                    self.log(f"あなたのターンです。")
                    self.human_action_needed = True
                    return 

            if not is_human and player_to_act:
                if player_to_act.is_cpu:
                    self.get_cpu_action(player_to_act)
                elif player_to_act.is_gemini:
                    self.get_gemini_poker_action(player_to_act)

    def handle_human_action(self, action, amount=0):
        if not self.human_action_needed: 
            return

        with self.action_lock:
            if not self.human_action_needed: # Double check inside lock
                return
            self.human_action_needed = False
            self.handle_action(action, amount)
        
        threading.Thread(target=self.process_turn, daemon=True).start()

    def get_cpu_action(self, player):
        amount_to_call = self.current_bet - player.bet
        action = 'check'
        if amount_to_call > 0:
            if random.random() < 0.7 or amount_to_call >= player.chips:
                action = 'call'
            else:
                action = 'fold'
        with self.action_lock:
            self.handle_action(action)

    def get_gemini_poker_action(self, player):
        # This runs in a separate thread and calls handle_action
        hand_str = ' '.join(map(lambda c: c.suit + c.rank, player.hand))
        community_str = ' '.join(map(lambda c: c.suit + c.rank, self.community_cards))
        player_states = [p.to_dict() for p in self.players]
        amount_to_call = self.current_bet - player.bet
        min_raise = self.current_bet * 2 if self.current_bet > 0 else self.big_blind_amount

        prompt = f"""
            You are a professional Texas Hold'em poker player. Analyze the game state and output your best action in JSON format.
            Game State:
            - Stage: {self.game_stage}
            - Your Hand: {hand_str}
            - Community Cards: {community_str or "None"}
            - Total Pot: {self.pot}
            - Your current bet in this round: {player.bet}
            - Amount to call: {amount_to_call}
            - Your remaining chips: {player.chips}
            - Player States: {json.dumps(player_states, indent=2)}
            
            Your possible actions:
            - `fold`: Forfeit the round.
            - `check`: Bet nothing (only if no call is required).
            - `call`: Match the current bet.
            - `raise`: Increase the bet. Specify the total amount in the `amount` field. Minimum raise to: {min_raise}.
            - `all-in`: Bet all your remaining chips.

            Output only the JSON object.
            {{ "action": "...", "amount": ... }}
            """
        try:
            self.log(f"{player.name} (Gemini) is thinking...")
            response = model.generate_content(prompt)
            json_part = response.text[response.text.find('{'):response.text.rfind('}')+1]
            action_data = json.loads(json_part)
            action = action_data.get("action", "fold")
            amount = action_data.get("amount", 0)
            self.log(f"Gemini's action: {action} {amount if action == 'raise' else ''}")
            with self.action_lock:
                self.handle_action(action, amount)
        except Exception as e:
            print(f"Gemini action error: {e}")
            with self.action_lock:
                self.handle_action("fold")

    def handle_action(self, action, amount=0):
        # This method should only be called from within a locked context
        player = self.players[self.current_player_index]
        
        if action == 'fold':
            player.is_folded = True
            self.log(f"{player.name} folds.")
        elif action == 'check':
            self.log(f"{player.name} checks.")
        elif action == 'call':
            amount_to_call = self.current_bet - player.bet
            if amount_to_call >= player.chips:
                self.log(f"{player.name} goes all-in to call.")
                player.bet += player.chips
                player.chips = 0
                player.is_all_in = True
            else:
                self.log(f"{player.name} calls {amount_to_call}.")
                player.chips -= amount_to_call
                player.bet += amount_to_call
        elif action == 'raise':
            # Validate raise amount
            min_raise = self.current_bet * 2 if self.current_bet > 0 else self.big_blind_amount
            amount = max(min_raise, amount)
            amount = min(amount, player.chips + player.bet)

            if amount >= player.chips + player.bet:
                action = 'all-in'
                amount = player.chips + player.bet
                player.is_all_in = True
                self.log(f"{player.name} raises all-in to {amount}!")
            else:
                self.log(f"{player.name} raises to {amount}.")

            amount_to_raise = amount - player.bet
            player.chips -= amount_to_raise
            player.bet = amount
            self.current_bet = player.bet
            # Reset has_acted for other players
            for p in self.players:
                if p != player and not p.is_folded and not p.is_all_in:
                    p.has_acted = False
        
        player.has_acted = True
        self.current_player_index = (self.current_player_index + 1) % len(self.players)

    def end_betting_round(self):
        # This method should only be called from within a locked context
        for p in self.players:
            self.pot += p.bet
            p.bet = 0
        
        next_stage = {"pre-flop": "flop", "flop": "turn", "turn": "river", "river": "showdown"}
        self.game_stage = next_stage[self.game_stage]

        if self.game_stage == "flop":
            self.community_cards.extend([self.deck.deal() for _ in range(3)])
            self.log(f"--- Flop ---")
        elif self.game_stage == "turn":
            self.community_cards.append(self.deck.deal())
            self.log(f"--- Turn ---")
        elif self.game_stage == "river":
            self.community_cards.append(self.deck.deal())
            self.log(f"--- River ---")
        elif self.game_stage == "showdown":
            self.end_round()
            return
        
        community_str = ' '.join(map(lambda c: c.suit + c.rank, self.community_cards))
        self.log(f"Community Cards: {community_str}")
        self.process_betting_round()

    def evaluate_hand(self, hand):
        all_hands = list(itertools.combinations(hand, 5))
        best_hand_rank = (-1, [])
        for h in all_hands:
            rank = self.get_hand_rank(h)
            if rank[0] > best_hand_rank[0] or (rank[0] == best_hand_rank[0] and sorted([c.value for c in rank[1]], reverse=True) > sorted([c.value for c in best_hand_rank[1]], reverse=True)):
                best_hand_rank = rank
        return best_hand_rank

    def get_hand_rank(self, hand):
        hand = sorted(hand, key=lambda card: card.value, reverse=True)
        values = [c.value for c in hand]; suits = [c.suit for c in hand]
        is_flush = len(set(suits)) == 1
        is_straight = (len(set(values)) == 5 and max(values) - min(values) == 4) or (values == [14, 5, 4, 3, 2])
        if is_straight and is_flush: return (8, hand) if values != [14, 13, 12, 11, 10] else (9, hand)
        counts = sorted({v: values.count(v) for v in set(values)}.items(), key=lambda item: (item[1], item[0]), reverse=True)
        if counts[0][1] == 4: return (7, sorted(hand, key=lambda c: (c.value != counts[0][0], c.value), reverse=True))
        if counts[0][1] == 3 and counts[1][1] == 2: return (6, hand)
        if is_flush: return (5, hand)
        if is_straight: return (4, [c for c in hand if c.value != 14] + [c for c in hand if c.value == 14]) if values == [14, 5, 4, 3, 2] else (4, hand)
        if counts[0][1] == 3: return (3, sorted(hand, key=lambda c: (c.value != counts[0][0], c.value), reverse=True))
        if counts[0][1] == 2 and counts[1][1] == 2: return (2, sorted(hand, key=lambda c: (c.value != counts[0][0] and c.value != counts[1][0], c.value), reverse=True))
        if counts[0][1] == 2: return (1, sorted(hand, key=lambda c: (c.value != counts[0][0], c.value), reverse=True))
        return (0, hand)

    def end_round(self):
        # This method should only be called from within a locked context
        self.pot += sum(p.bet for p in self.players)
        for p in self.players: p.bet = 0

        active_players = [p for p in self.players if not p.is_folded]
        
        self.log("--- Round End ---")
        for p in self.players: p.show_hand = True

        if len(active_players) == 1:
            winner = active_players[0]
            winner.chips += self.pot
            self.log(f"{winner.name} wins the pot ({self.pot})!")
        else:
            winner_data = sorted([{"player": p, "rank": self.evaluate_hand(p.hand + self.community_cards)} for p in active_players], key=lambda x: (x["rank"][0], [c.value for c in x["rank"][1]]), reverse=True)
            best_rank_tuple = (winner_data[0]["rank"][0], [c.value for c in winner_data[0]["rank"][1]])
            winners = [d for d in winner_data if (d["rank"][0], [c.value for c in d["rank"][1]]) == best_rank_tuple]
            
            winnings = self.pot // len(winners)
            for w_data in winners:
                w_data["player"].chips += winnings
            
            hand_names = ["High Card", "One Pair", "Two Pair", "Three of a Kind", "Straight", "Flush", "Full House", "Four of a Kind", "Straight Flush", "Royal Flush"]
            win_hand_name = hand_names[winner_data[0]["rank"][0]]
            winner_names = ", ".join([w["player"].name for w in winners])
            
            self.log(f"{winner_names} win(s) the pot ({self.pot}) with {win_hand_name}!")
            
        self.game_in_progress = False
        self.log("ラウンド終了。次のラウンドを開始するにはボタンを押してください。");

# --- Flask App ---
app = Flask(__name__)
# Use a global variable for the game instance. 
# For a real-world app, you'd manage sessions differently.
game = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_game', methods=['POST'])
def start_game_route():
    global game
    data = request.json
    game = PokerGame(
        human_player_name=data['name'],
        cpu_players=data['cpu_players'],
        gemini_players=data['gemini_players']
    )
    game.start_game_thread()
    return jsonify({"success": True})

@app.route('/game_state')
def game_state_route():
    if not game:
        return jsonify({"error": "Game not started"}), 404
    return jsonify(game.get_state())

@app.route('/player_action', methods=['POST'])
def player_action_route():
    if not game or not game.human_action_needed:
        return jsonify({"error": "Not your turn or game not ready"}), 400
    data = request.json
    action = data.get('action')
    amount = data.get('amount', 0)
    game.handle_human_action(action, amount)
    return jsonify({"success": True})

@app.route('/next_round', methods=['POST'])
def next_round_route():
    if not game or game.game_in_progress:
        return jsonify({"error": "Cannot start next round now"}), 400
    game.start_round() # Re-use start_round to begin the next hand
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(debug=True, port=5001)
