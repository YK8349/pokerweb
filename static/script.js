document.addEventListener('DOMContentLoaded', () => {
    const setupFrame = document.getElementById('setup-frame');
    const gameFrame = document.getElementById('game-frame');
    const startGameBtn = document.getElementById('start-game-btn');
    const playerNameInput = document.getElementById('player-name');
    const cpuPlayersInput = document.getElementById('cpu-players');
    const geminiPlayersInput = document.getElementById('gemini-players');

    const potEl = document.getElementById('pot');
    const communityCardsEl = document.getElementById('community-cards');
    const playersContainer = document.getElementById('players-container');
    const logBox = document.getElementById('log-box');
    const actionButtons = document.getElementById('action-buttons');

    const nextRoundBtn = document.getElementById('next-round-btn');

    let gameStateInterval = null;

    // --- Setup --- 
    startGameBtn.addEventListener('click', async () => {
        const playerName = playerNameInput.value;
        const cpuPlayers = parseInt(cpuPlayersInput.value);
        const geminiPlayers = parseInt(geminiPlayersInput.value);

        if (cpuPlayers + geminiPlayers < 1) {
            alert('対戦相手を1人以上指定してください。');
            return;
        }
        if (cpuPlayers + geminiPlayers > 7) {
            alert('CPUとGeminiの合計は7人以下にしてください。');
            return;
        }

        const response = await fetch('/start_game', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                name: playerName, 
                cpu_players: cpuPlayers, 
                gemini_players: geminiPlayers 
            }),
        });

        if (response.ok) {
            setupFrame.style.display = 'none';
            gameFrame.style.display = 'flex';
            gameStateInterval = setInterval(fetchGameState, 1000); // 1秒ごとにゲーム状態を更新
        } else {
            alert('ゲームの開始に失敗しました。');
        }
    });

    // --- Game Logic ---
    async function fetchGameState() {
        try {
            const response = await fetch('/game_state');
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            const state = await response.json();
            updateUI(state);
        } catch (error) {
            console.error('Failed to fetch game state:', error);
            clearInterval(gameStateInterval); // Stop polling on error
        }
    }

    function updateUI(state) {
        if (!state) return;

        // Show/hide next round button
        if (!state.game_in_progress && state.players.length > 0) {
            nextRoundBtn.style.display = 'block';
            disableActionButtons();
        } else {
            nextRoundBtn.style.display = 'none';
        }

        // Update Pot and Community Cards
        const totalPot = state.pot + state.players.reduce((acc, p) => acc + p.bet, 0);
        potEl.textContent = `Pot: ${totalPot}`;
        communityCardsEl.innerHTML = state.community_cards.map(c => createCardHtml(c)).join('');

        // Update Players
        updatePlayerSeats(state.players, state.current_player_index);

        // Update Logs
        logBox.innerHTML = state.log.join('<br>');
        logBox.scrollTop = logBox.scrollHeight;

        // Update Action Buttons
        const humanPlayer = state.players.find(p => !p.is_cpu && !p.is_gemini);
        if (state.human_action_needed && humanPlayer) {
            enableActionButtons(humanPlayer, state.current_bet);
        } else {
            disableActionButtons();
        }
    }

    function createCardHtml(card) {
        if (!card) return '';
        const suit = card.suit;
        const rank = card.rank;
        const suitClass = `suit-${suit}`;
        return `<div class="card ${suitClass}">${suit}${rank}</div>`;
    }

    function updatePlayerSeats(players, currentPlayerIndex) {
        playersContainer.innerHTML = ''; // Clear existing seats
        const numPlayers = players.length;
        const angleStep = 360 / numPlayers;
        const radius = 280; // in pixels

        players.forEach((player, i) => {
            const angle = (angleStep * i) - 90; // Start from top
            const x = 50 + (radius / 700 * 100) * Math.cos(angle * Math.PI / 180);
            const y = 50 + (radius / 700 * 100) * Math.sin(angle * Math.PI / 180);

            const seat = document.createElement('div');
            seat.className = 'player-seat';
            seat.style.left = `calc(${x}% - 60px)`;
            seat.style.top = `calc(${y}% - 50px)`;

            if (i === currentPlayerIndex) {
                seat.classList.add('active');
            }

            let status = '';
            if (player.is_folded) status = '<div class="player-status">Fold</div>';
            if (player.is_all_in) status = '<div class="player-status">All-in</div>';

            let handHtml = '';
            if (player.show_hand) {
                handHtml = player.hand.map(c => createCardHtml(c)).join('');
            } else {
                handHtml = `<div class="card hidden"></div><div class="card hidden"></div>`;
            }

            seat.innerHTML = `
                <div class="player-name">${player.name}</div>
                <div class="player-chips">Chips: ${player.chips}</div>
                <div class="player-bet">Bet: ${player.bet}</div>
                ${status}
                <div class="player-hand">${handHtml}</div>
            `;
            playersContainer.appendChild(seat);
        });
    }

    function enableActionButtons(player, currentBet) {
        const amountToCall = currentBet - player.bet;
        document.getElementById('fold-btn').disabled = false;
        
        if (amountToCall <= 0) {
            document.getElementById('check-btn').disabled = false;
            document.getElementById('call-btn').disabled = true;
            document.getElementById('call-btn').textContent = 'コール';
        } else {
            document.getElementById('check-btn').disabled = true;
            document.getElementById('call-btn').disabled = false;
            document.getElementById('call-btn').textContent = `コール (${amountToCall})`;
            if (player.chips <= amountToCall) {
                 document.getElementById('call-btn').textContent = 'オールイン';
            }
        }

        document.getElementById('raise-btn').disabled = player.chips <= amountToCall;
    }

    function disableActionButtons() {
        document.querySelectorAll('.action-btn').forEach(btn => btn.disabled = true);
    }

    actionButtons.addEventListener('click', (e) => {
        if (!e.target.matches('.action-btn')) return;

        const action = e.target.dataset.action;
        let amount = 0;

        if (action === 'raise') {
            // Simplified prompt for web version
            const playerResponse = prompt('レイズ後の合計ベット額を入力してください:', '');
            amount = parseInt(playerResponse);
            if (isNaN(amount) || amount <= 0) {
                return; // Cancel if invalid amount
            }
        }
        sendPlayerAction(action, amount);
    });

    nextRoundBtn.addEventListener('click', async () => {
        nextRoundBtn.style.display = 'none';
        await fetch('/next_round', { method: 'POST' });
        // The game state will be updated by the next poll
    });

    async function sendPlayerAction(action, amount = 0) {
        disableActionButtons();
        await fetch('/player_action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, amount }),
        });
        // The game state will be updated by the next poll
    }
});
